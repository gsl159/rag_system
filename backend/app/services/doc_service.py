"""Backward compatibility — imports from app.service.doc_service"""
from app.service.doc_service import (
    DocParser, TextCleaner, TextSplitter, QualityChecker,
    DocumentService, doc_service,
)

__all__ = [
    "DocParser", "TextCleaner", "TextSplitter", "QualityChecker",
    "DocumentService", "doc_service",
]
