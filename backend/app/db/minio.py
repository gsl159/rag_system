"""Backward compatibility — imports from app.repository.object_store"""
from app.repository.object_store import minio_storage, MinioStorage

__all__ = ["minio_storage", "MinioStorage"]
