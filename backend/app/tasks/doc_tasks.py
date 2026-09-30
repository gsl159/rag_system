"""
文档处理 Celery 任务

worker 以同步方式运行，内部通过 asyncio.run 驱动异步处理逻辑。
失败时自动重试（指数退避），超过重试次数后把文档标记为 failed。
"""
import asyncio
import os

from celery import shared_task
from celery.utils.log import get_task_logger

from app.core.logger import logger as app_logger

task_logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    name="app.tasks.doc_tasks.process_document",
    autoretry_for=(Exception,),
    retry_backoff=True,       # 指数退避
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def process_document(self, doc_id: str, tenant_id: str = "default"):
    """处理文档：下载 -> 解析 -> 分块 -> 向量化 -> 入库"""
    from app.db.postgres import AsyncSessionLocal, set_current_tenant, Document
    from app.db.minio import minio_storage
    from app.services.doc_service import doc_service
    from sqlalchemy import select, update

    task_logger.info(f"[Celery] 开始处理文档 doc_id={doc_id} tenant={tenant_id} attempt={self.request.retries}")

    # 设置租户上下文（供 RLS 与 Milvus 向量过滤）
    set_current_tenant(tenant_id)

    async def _run():
        async with AsyncSessionLocal() as db:
            # 取文档对象名
            result = await db.execute(select(Document).where(Document.id == doc_id))
            doc = result.scalar_one_or_none()
            if not doc:
                raise ValueError(f"文档不存在: {doc_id}")

            # 从 MinIO 下载到本地临时文件
            import tempfile
            suffix = os.path.splitext(doc.filename or "")[1]
            content = await minio_storage.download_bytes(doc.file_path)
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                await doc_service.process(doc_id, tmp_path, db, tenant_id=tenant_id)
            finally:
                os.unlink(tmp_path)

    try:
        asyncio.run(_run())
        task_logger.info(f"[Celery] 文档处理完成 doc_id={doc_id}")
    except Exception as e:
        app_logger.error(f"[Celery] 文档处理失败 doc_id={doc_id}: {e}")
        # 最后一次重试仍失败 -> 标记 failed
        if self.request.retries >= self.max_retries:
            asyncio.run(_mark_failed(doc_id, tenant_id, str(e)))
            task_logger.error(f"[Celery] 文档最终失败并已标记 doc_id={doc_id}")
            return {"doc_id": doc_id, "status": "failed", "error": str(e)}
        raise

    return {"doc_id": doc_id, "status": "done"}


async def _mark_failed(doc_id: str, tenant_id: str, error: str):
    from app.db.postgres import AsyncSessionLocal, set_current_tenant, Document
    from sqlalchemy import update
    set_current_tenant(tenant_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Document).where(Document.id == doc_id).values(
                status="failed", error_msg=error[:500]
            )
        )
        await db.commit()
