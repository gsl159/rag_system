"""
/upload 路由 — 文档上传与管理

- 上传：写 MinIO + PG，随后按大小/配置决定走 Celery 队列或进程内后台任务
- 删除：联动清理 MinIO + Milvus（租户内）+ PG（RLS 自动限定租户）
"""
import os
import uuid
import tempfile
from typing import List

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import logger
from app.core.limiter import limiter
from app.db.postgres import get_db, Document, Chunk, get_current_tenant
from app.db.minio import minio_storage
from app.db.milvus import milvus_db
from app.services.doc_service import doc_service

router = APIRouter(prefix="/upload", tags=["文档管理"])

ALLOWED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/html", "text/plain", "text/markdown",
}
ALLOWED_EXTS  = {".pdf", ".docx", ".doc", ".html", ".htm", ".txt", ".md"}


@router.post("/")
@limiter.limit(settings.RATE_LIMIT_UPLOAD)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db:   AsyncSession = Depends(get_db),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"不支持的文件类型 '{ext}'，支持：{', '.join(ALLOWED_EXTS)}")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "文件内容为空")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(400, "文件大小不能超过 50MB")

    tenant_id = get_current_tenant()
    doc_id    = str(uuid.uuid4())
    obj_key   = f"{tenant_id}/{doc_id}{ext}"

    # 上传 MinIO（异步）
    await minio_storage.upload(obj_key, content, file.content_type or "application/octet-stream")

    # 写 DB
    doc = Document(
        id        = doc_id,
        tenant_id = tenant_id,
        filename  = file.filename,
        file_path = obj_key,
        file_type = ext,
        file_size = len(content),
        status    = "pending",
    )
    db.add(doc)
    await db.commit()

    # 分派处理：大文件或强制模式下走 Celery，否则进程内后台任务
    use_celery = settings.CELERY_ALWAYS or (len(content) > settings.CELERY_SIZE_THRESHOLD_MB * 1024 * 1024)
    if use_celery:
        try:
            from app.tasks.doc_tasks import process_document
            process_document.delay(doc_id, tenant_id)
            logger.info(f"文档 {doc_id} 已投递 Celery 队列")
            return {"doc_id": doc_id, "filename": file.filename, "status": "queued"}
        except Exception as e:
            logger.warning(f"Celery 投递失败，回退进程内处理: {e}")

    async def _process():
        from app.db.postgres import AsyncSessionLocal, set_current_tenant
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            # 后台任务不在请求上下文中，需自行设置租户（供 RLS 与向量过滤）
            set_current_tenant(tenant_id)
            async with AsyncSessionLocal() as sess:
                await doc_service.process(doc_id, tmp_path, sess, tenant_id=tenant_id)
        except Exception as e:
            logger.error(f"后台处理失败 {doc_id}: {e}")
        finally:
            os.unlink(tmp_path)

    background_tasks.add_task(_process)
    return {"doc_id": doc_id, "filename": file.filename, "status": "processing"}


@router.get("/docs")
async def list_docs(skip: int = 0, limit: int = 30, db: AsyncSession = Depends(get_db)):
    # RLS 已在会话层限定 tenant_id
    result = await db.execute(
        select(Document).order_by(Document.created_at.desc()).offset(skip).limit(limit)
    )
    docs = result.scalars().all()
    return [
        {
            "id":          d.id,
            "filename":    d.filename,
            "file_type":   d.file_type,
            "file_size":   d.file_size,
            "status":      d.status,
            "parse_score": round(d.parse_score or 0, 3),
            "chunk_count": d.chunk_count,
            "error_msg":   d.error_msg,
            "created_at":  d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


@router.delete("/docs/{doc_id}")
async def delete_doc(doc_id: str, db: AsyncSession = Depends(get_db)):
    tenant_id = get_current_tenant()
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc    = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "文档不存在")

    try:
        await minio_storage.delete(doc.file_path)
    except Exception as e:
        logger.warning(f"MinIO 删除失败 {doc.file_path}: {e}")

    try:
        # 在租户内删除向量（Milvus 标量过滤）
        await milvus_db.delete_by_doc(doc_id, tenant_id=tenant_id)
    except Exception as e:
        logger.warning(f"Milvus 删除失败 doc_id={doc_id}: {e}")

    await db.delete(doc)
    await db.commit()
    return {"message": "删除成功", "doc_id": doc_id}
