"""
MinIO 对象存储

- 延迟初始化：客户端在首次使用时才建立连接，避免模块导入即阻塞（进程中无 MinIO 时不再挂起）
- 异步：所有 IO 通过 asyncio.to_thread 执行，不阻塞事件循环
"""
import asyncio
import io
from typing import Optional

from minio import Minio
from minio.error import S3Error
from app.core.config import settings
from app.core.logger import logger


class MinioStorage:
    def __init__(self):
        self._client: Optional[Minio] = None
        self._bucket = settings.MINIO_BUCKET

    def _get_client(self) -> Minio:
        """惰性创建客户端并确保 bucket 存在"""
        if self._client is None:
            self._client = Minio(
                settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
            )
            try:
                if not self._client.bucket_exists(self._bucket):
                    self._client.make_bucket(self._bucket)
                    logger.info(f"MinIO bucket '{self._bucket}' 创建成功")
            except S3Error as e:
                logger.error(f"MinIO 初始化失败: {e}")
        return self._client

    def _upload_sync(self, object_name: str, data: bytes, content_type: str) -> str:
        client = self._get_client()
        client.put_object(
            self._bucket, object_name,
            io.BytesIO(data), len(data),
            content_type=content_type,
        )
        return object_name

    async def upload(self, object_name: str, data: bytes,
                     content_type: str = "application/octet-stream") -> str:
        result = await asyncio.to_thread(self._upload_sync, object_name, data, content_type)
        logger.debug(f"MinIO 上传: {object_name}")
        return result

    def _download_sync(self, object_name: str) -> bytes:
        client = self._get_client()
        resp = client.get_object(self._bucket, object_name)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    async def download_bytes(self, object_name: str) -> bytes:
        return await asyncio.to_thread(self._download_sync, object_name)

    def _delete_sync(self, object_name: str):
        self._get_client().remove_object(self._bucket, object_name)

    async def delete(self, object_name: str):
        await asyncio.to_thread(self._delete_sync, object_name)


minio_storage = MinioStorage()
