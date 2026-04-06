"""Backward compatibility — imports from app.repository.vector_store"""
from app.repository.vector_store import milvus_db, MilvusDB

__all__ = ["milvus_db", "MilvusDB"]
