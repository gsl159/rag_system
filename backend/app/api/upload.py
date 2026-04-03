"""
/upload 路由 — 文档上传与管理
"""
import os
import uuid
import tempfile
from typing import List

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.db.postgres import get_db, Document, Chunk
from app.db.minio import minio_storage
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
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db:   AsyncSession = Depends(get_db),
):
    # 校验文件类型
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"不支持的文件类型 '{ext}'，支持：{', '.join(ALLOWED_EXTS)}")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "文件内容为空")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(400, "文件大小不能超过 50MB")

    doc_id  = str(uuid.uuid4())
    obj_key = f"{doc_id}{ext}"

    # 上传 MinIO
    minio_storage.upload(obj_key, content, file.content_type or "application/octet-stream")

    # 写 DB
    doc = Document(
        id        = doc_id,
        filename  = file.filename,
        file_path = obj_key,
        file_type = ext,
        file_size = len(content),
        status    = "pending",
    )
    db.add(doc)
    await db.commit()

    # 后台异步处理
    async def _process():
        from app.db.postgres import AsyncSessionLocal
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            async with AsyncSessionLocal() as sess:
                await doc_service.process(doc_id, tmp_path, sess)
        except Exception as e:
            logger.error(f"后台处理失败 {doc_id}: {e}")
        finally:
            os.unlink(tmp_path)

    background_tasks.add_task(_process)
    return {"doc_id": doc_id, "filename": file.filename, "status": "processing"}


@router.get("/docs")
async def list_docs(skip: int = 0, limit: int = 30, db: AsyncSession = Depends(get_db)):
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
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc    = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "文档不存在")

    try: minio_storage.delete(doc.file_path)
    except Exception: pass

    from app.db.milvus import milvus_db
    try: milvus_db.delete_by_doc(doc_id)
    except Exception: pass

    await db.delete(doc)
    await db.commit()
    return {"message": "删除成功", "doc_id": doc_id}
