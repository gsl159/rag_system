"""Backward compatibility — imports from app.repository.postgres"""
from app.repository.postgres import (
    engine, AsyncSessionLocal, Base, User, Document, Chunk,
    QueryLog, Evaluation, Feedback, AuditLog, get_db, init_db,
)

__all__ = [
    "engine", "AsyncSessionLocal", "Base", "User", "Document", "Chunk",
    "QueryLog", "Evaluation", "Feedback", "AuditLog", "get_db", "init_db",
]
