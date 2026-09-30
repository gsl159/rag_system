"""
可观测性 — OpenTelemetry 链路追踪

启用后（OTEL_ENABLED=true）通过 OTLP 上报到 Jaeger，
对 RAG Pipeline 的每个 Step（Rewrite/Embed/Retrieve/Rerank/LLM）做耗时埋点。
未启用时 span 为空操作（no-op），不影响性能。
"""
from contextlib import contextmanager
from typing import Generator

from app.core.config import settings
from app.core.logger import logger

_tracer = None


def init_tracing():
    """初始化全局 Tracer（幂等）"""
    global _tracer
    if _tracer is not None or not settings.OTEL_ENABLED:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        resource = Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("rag")
        logger.info(f"✅ OpenTelemetry 已启用 -> {settings.OTEL_EXPORTER_OTLP_ENDPOINT}")
    except Exception as e:
        logger.error(f"❌ OpenTelemetry 初始化失败: {e}")


@contextmanager
def trace_step(name: str, **attrs) -> Generator:
    """
    为 Pipeline 的单个 Step 创建 span。
    用法：
        with trace_step("retrieve", top_k=10) as span:
            ...
            span.set_attribute("hits", len(docs))
    """
    if _tracer is None:
        yield _NoopSpan()
        return
    with _tracer.start_as_current_span(name) as span:
        for k, v in attrs.items():
            try:
                span.set_attribute(k, v)
            except Exception:
                pass
        yield span


class _NoopSpan:
    def set_attribute(self, *args, **kwargs): pass
    def record_exception(self, *args, **kwargs): pass
