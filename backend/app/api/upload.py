"""
/upload 路由 — 文档上传管理，含审计
"""
import hashlib, os, uuid, tempfile
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ok
from app.core.security import get_current_user, generate_trace_id
from app.db.postgres import get_db, Document, AuditLog
from app.db.minio import minio_storage
from app.db.redis import cache
from app.services.doc_service import doc_service

router = APIRouter(prefix="/upload", tags=["文档管理"])
ALLOWED_EXTS = {".pdf", ".docx", ".doc", ".html", ".htm", ".txt", ".md"}


@router.post("/")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    trace_id = generate_trace_id()
    if not file.filename:
        raise HTTPException(400, detail={"code": 1001, "message": "文件名不能为空"})
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, detail={"code": 1001, "message": f"不支持 '{ext}' 格式"})

    content = await file.read()
    if not content:
        raise HTTPException(400, detail={"code": 1001, "message": "文件为空"})
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(400, detail={"code": 1001, "message": "文件超过50MB"})

    file_md5 = hashlib.md5(content).hexdigest()
    dup = await db.execute(select(Document).where(Document.file_path.contains(file_md5)))
    if dup.scalar_one_or_none():
        raise HTTPException(409, detail={"code": 1001, "message": "相同文件已存在（MD5重复）"})

    doc_id  = str(uuid.uuid4())
    obj_key = f"{file_md5}{ext}"
    try:
        minio_storage.upload(obj_key, content, file.content_type or "application/octet-stream")
    except Exception as e:
        raise HTTPException(500, detail={"code": 5000, "message": "文件存储失败"})

    doc = Document(id=doc_id, filename=file.filename, file_path=obj_key,
                   file_type=ext, file_size=len(content), status="pending",
                   tenant_id=user.get("tenant_id", "default"))
    db.add(doc)
    db.add(AuditLog(trace_id=trace_id, user_id=user.get("sub"), action="upload",
                    resource=file.filename, ip=request.client.host if request.client else None))
    await db.commit()

    background_tasks.add_task(_process_document, doc_id, ext, content)
    return ok({"doc_id": doc_id, "filename": file.filename, "status": "processing"}, trace_id=trace_id)


async def _process_document(doc_id: str, ext: str, content: bytes):
    from app.db.postgres import AsyncSessionLocal
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content); tmp_path = tmp.name
        async with AsyncSessionLocal() as sess:
            await doc_service.process(doc_id, tmp_path, sess)
        await cache.increment_doc_version()
    except Exception as e:
        from app.core.logger import logger
        logger.error(f"后台处理失败 {doc_id}: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.unlink(tmp_path)
            except: pass


@router.get("/docs")
async def list_docs(
    skip: int = 0, limit: int = 30,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    limit = min(limit, 100)
    result = await db.execute(
        select(Document).order_by(Document.created_at.desc()).offset(skip).limit(limit)
    )
    docs = result.scalars().all()
    return ok([{
        "id": d.id, "filename": d.filename, "file_type": d.file_type,
        "file_size": d.file_size, "status": d.status,
        "parse_score": round(float(d.parse_score or 0), 3),
        "chunk_count": d.chunk_count, "doc_version": d.doc_version,
        "error_msg": d.error_msg,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    } for d in docs])


@router.get("/docs/{doc_id}")
async def get_doc(doc_id: str, db: AsyncSession = Depends(get_db),
                  user: dict = Depends(get_current_user)):
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, detail={"code": 1001, "message": "文档不存在"})
    return ok({"id": doc.id, "filename": doc.filename, "file_type": doc.file_type,
               "status": doc.status, "parse_score": round(float(doc.parse_score or 0), 3),
               "chunk_count": doc.chunk_count, "error_msg": doc.error_msg,
               "created_at": doc.created_at.isoformat() if doc.created_at else None})


@router.delete("/docs/{doc_id}")
async def delete_doc(
    doc_id: str, request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, detail={"code": 1001, "message": "文档不存在"})

    try: minio_storage.delete(doc.file_path)
    except: pass
    from app.db.milvus import milvus_db
    try: milvus_db.delete_by_doc(doc_id)
    except: pass

    db.add(AuditLog(user_id=user.get("sub"), action="delete_doc",
                    resource=doc.filename, ip=request.client.host if request.client else None))
    await db.delete(doc)
    await db.commit()
    await cache.increment_doc_version()
    return ok({"doc_id": doc_id, "message": "删除成功"})
