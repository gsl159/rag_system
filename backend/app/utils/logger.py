"""Structured logging with trace_id integration."""
import sys
import os

from loguru import logger

from app.config.settings import settings
from app.utils.trace import get_trace_id


def _trace_filter(record):
    """Inject trace_id into every log record."""
    record["extra"]["trace_id"] = get_trace_id() or "-"
    return True


def setup_logger():
    logger.remove()

    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "trace_id={extra[trace_id]} | "
        "<level>{message}</level>"
    )

    logger.add(sys.stdout, format=fmt, level=settings.LOG_LEVEL,
               colorize=True, filter=_trace_filter)

    os.makedirs("logs", exist_ok=True)
    logger.add(
        "logs/app_{time:YYYY-MM-DD}.log",
        format=fmt,
        level=settings.LOG_LEVEL,
        rotation="00:00",
        retention="30 days",
        compression="zip",
        encoding="utf-8",
        filter=_trace_filter,
    )
    return logger


setup_logger()

__all__ = ["logger"]
