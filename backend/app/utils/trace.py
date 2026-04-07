"""Trace ID generation and propagation across all layers."""
import uuid
from contextvars import ContextVar

# Context variable for trace_id propagation across async layers
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def generate_trace_id() -> str:
    """Generate a 16-character trace ID."""
    return uuid.uuid4().hex[:16]


def get_trace_id() -> str:
    """Get the current trace_id from context."""
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    """Set the trace_id in current context."""
    _trace_id_var.set(trace_id)
