"""Backward compatibility — imports from app.service.feedback_service"""
from app.service.feedback_service import FeedbackService, feedback_service

__all__ = ["FeedbackService", "feedback_service"]
