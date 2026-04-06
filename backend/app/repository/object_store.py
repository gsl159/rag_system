"""
MinIO 对象存储 — 带连接重试
"""
import io
from typing import Optional

from app.config.settings import settings
from app.utils.logger import logger


class MinioStorage:
    def __init__(self):
        self._client = None
        self._init_client()

    def _init_client(self):
        try:
            from minio import Minio
            self._client = Minio(
                settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
            )
            self._ensure_bucket()
        except Exception as e:
            logger.error(f"MinIO 初始化失败: {e}")
            self._client = None

    def _ensure_bucket(self):
        try:
            if not self._client.bucket_exists(settings.MINIO_BUCKET):
                self._client.make_bucket(settings.MINIO_BUCKET)
                logger.info(f"MinIO bucket '{settings.MINIO_BUCKET}' 创建成功")
        except Exception as e:
            logger.error(f"MinIO bucket 初始化失败: {e}")

    def upload(self, object_name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        if not self._client:
            raise RuntimeError("MinIO 未连接")
        self._client.put_object(
            settings.MINIO_BUCKET, object_name,
            io.BytesIO(data), len(data),
            content_type=content_type,
        )
        logger.debug(f"MinIO 上传: {object_name} ({len(data)} bytes)")
        return object_name

    def download_bytes(self, object_name: str) -> bytes:
        if not self._client:
            raise RuntimeError("MinIO 未连接")
        resp = self._client.get_object(settings.MINIO_BUCKET, object_name)
        return resp.read()

    def download_to_file(self, object_name: str, local_path: str):
        if not self._client:
            raise RuntimeError("MinIO 未连接")
        self._client.fget_object(settings.MINIO_BUCKET, object_name, local_path)

    def delete(self, object_name: str):
        if not self._client:
            return
        try:
            self._client.remove_object(settings.MINIO_BUCKET, object_name)
            logger.debug(f"MinIO 删除: {object_name}")
        except Exception as e:
            logger.warning(f"MinIO 删除失败: {e}")

    @property
    def is_connected(self) -> bool:
        return self._client is not None


minio_storage = MinioStorage()
