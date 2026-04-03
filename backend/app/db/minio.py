"""
MinIO 对象存储
"""
import io
from minio import Minio
from minio.error import S3Error
from app.core.config import settings
from app.core.logger import logger


class MinioStorage:
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self._init_bucket()

    def _init_bucket(self):
        try:
            if not self.client.bucket_exists(settings.MINIO_BUCKET):
                self.client.make_bucket(settings.MINIO_BUCKET)
                logger.info(f"MinIO bucket '{settings.MINIO_BUCKET}' 创建成功")
        except S3Error as e:
            logger.error(f"MinIO 初始化失败: {e}")

    def upload(self, object_name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(
            settings.MINIO_BUCKET, object_name,
            io.BytesIO(data), len(data),
            content_type=content_type,
        )
        logger.debug(f"MinIO 上传: {object_name}")
        return object_name

    def download_bytes(self, object_name: str) -> bytes:
        resp = self.client.get_object(settings.MINIO_BUCKET, object_name)
        return resp.read()

    def download_to_file(self, object_name: str, local_path: str):
        self.client.fget_object(settings.MINIO_BUCKET, object_name, local_path)

    def delete(self, object_name: str):
        self.client.remove_object(settings.MINIO_BUCKET, object_name)


minio_storage = MinioStorage()
