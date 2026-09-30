"""
Celery 应用 — 分布式异步任务队列

用于把「文档解析 + 向量化」这类耗时任务从 FastAPI 主进程剥离，
支持任务重试与失败告警。Broker/Backend 均使用 Redis。
"""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "rag",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 可靠性：晚确认 + 预取 1，避免 worker 崩溃丢任务
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # 失败重试策略
    task_default_retry_delay=10,
    task_max_retries=3,
    # 结果过期
    result_expires=3600,
    task_track_started=True,
)

# 显式导入任务模块，确保 worker 启动时完成注册
celery_app.autodiscover_tasks(["app.tasks"])
from app.tasks import doc_tasks  # noqa: E402,F401
