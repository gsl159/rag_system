"""
统一日志配置 — loguru
"""
import sys
import os
from loguru import logger
from app.core.config import settings


def setup_logger():
    logger.remove()

    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    # 控制台
    logger.add(sys.stdout, format=fmt, level=settings.LOG_LEVEL, colorize=True)

    # 文件（按天轮转）
    os.makedirs("logs", exist_ok=True)
    logger.add(
        "logs/app_{time:YYYY-MM-DD}.log",
        format=fmt,
        level=settings.LOG_LEVEL,
        rotation="00:00",
        retention="30 days",
        compression="zip",
        encoding="utf-8",
    )

    return logger


setup_logger()

__all__ = ["logger"]
