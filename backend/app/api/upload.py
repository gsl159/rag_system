"""
/upload 路由 — 文档上传与管理
上传后递增 doc_version 使缓存自动失效
"""
import hashlib
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
from app.db.redis import cache
from app.services.doc_service import doc_service

router = APIRouter(prefix="/upload", tags=["文档管理"])

ALLOWED_EXTS = {".pdf", ".docx", ".doc", ".html", ".htm", ".txt", ".md"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@router.post("/")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db:   AsyncSession = Depends(get_db),
):
    """上传文档，后台异步处理"""
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"不支持的文件类型 '{ext}'，支持：{', '.join(ALLOWED_EXTS)}")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "文件内容为空")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "文件大小不能超过 50MB")

    # MD5 去重
    file_md5 = hashlib.md5(content).hexdigest()
    exists = await db.execute(
        select(Document).where(Document.file_path.contains(file_md5))
    )
    if exists.scalar_one_or_none():
        raise HTTPException(409, "相同文件已存在（MD5重复），请勿重复上传")

    doc_id  = str(uuid.uuid4())
    obj_key = f"{file_md5}{ext}"  # 用MD5作为文件名实现去重存储

    # 上传 MinIO
    try:
        minio_storage.upload(obj_key, content, file.content_type or "application/octet-stream")
    except Exception as e:
        logger.error(f"MinIO 上传失败: {e}")
        raise HTTPException(500, "文件存储失败，请稍后重试")

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
    background_tasks.add_task(_process_document, doc_id, ext, content)

    return {"doc_id": doc_id, "filename": file.filename, "status": "processing"}


async def _process_document(doc_id: str, ext: str, content: bytes):
    """后台文档处理任务"""
    from app.db.postgres import AsyncSessionLocal
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        async with AsyncSessionLocal() as sess:
            await doc_service.process(doc_id, tmp_path, sess)

        # 文档处理完成，递增全局 doc_version 使缓存失效
        await cache.increment_doc_version()
        logger.info(f"文档 {doc_id} 处理完成，已递增 doc_version")

    except Exception as e:
        logger.error(f"后台处理失败 {doc_id}: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


@router.get("/docs")
async def list_docs(skip: int = 0, limit: int = 30, db: AsyncSession = Depends(get_db)):
    """获取文档列表"""
    if limit > 100:
        limit = 100
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
            "parse_score": round(float(d.parse_score or 0), 3),
            "chunk_count": d.chunk_count,
            "doc_version": d.doc_version,
            "error_msg":   d.error_msg,
            "created_at":  d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


@router.get("/docs/{doc_id}")
async def get_doc(doc_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个文档详情"""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "文档不存在")
    return {
        "id":          doc.id,
        "filename":    doc.filename,
        "file_type":   doc.file_type,
        "file_size":   doc.file_size,
        "status":      doc.status,
        "parse_score": round(float(doc.parse_score or 0), 3),
        "chunk_count": doc.chunk_count,
        "doc_version": doc.doc_version,
        "error_msg":   doc.error_msg,
        "created_at":  doc.created_at.isoformat() if doc.created_at else None,
    }


@router.delete("/docs/{doc_id}")
async def delete_doc(doc_id: str, db: AsyncSession = Depends(get_db)):
    """删除文档及其所有关联数据"""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc    = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "文档不存在")

    # 删除 MinIO 文件
    try:
        minio_storage.delete(doc.file_path)
    except Exception as e:
        logger.warning(f"MinIO 删除失败（继续）: {e}")

    # 删除 Milvus 向量
    from app.db.milvus import milvus_db
    try:
        milvus_db.delete_by_doc(doc_id)
    except Exception as e:
        logger.warning(f"Milvus 删除失败（继续）: {e}")

    # 删除 DB 记录（Chunk 通过外键级联删除）
    await db.delete(doc)
    await db.commit()

    # 递增 doc_version 使缓存失效
    await cache.increment_doc_version()

    return {"message": "删除成功", "doc_id": doc_id}
