import os
from typing import Any

try:
    from ddtrace import config, tracer
    from ddtrace.propagation.http import HTTPPropagator
except ImportError:  # pragma: no cover
    config = None
    tracer = None
    HTTPPropagator = None


def service_name() -> str:
    return os.getenv("DD_SERVICE", "billing-service")


def configure_tracing() -> None:
    if config is not None and hasattr(config, "psycopg"):
        config.psycopg["service"] = os.getenv("DD_PSYCOPG_SERVICE", "billing-service-db")


def capture_current_trace_headers() -> dict[str, str]:
    if tracer is None or HTTPPropagator is None:
        return {}

    span = tracer.current_span()
    if span is None:
        return {}

    carrier: dict[str, str] = {}
    HTTPPropagator.inject(span.context, carrier)
    return carrier


def inject_trace_headers(headers: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = headers or {}
    if tracer is None or HTTPPropagator is None:
        return headers

    span = tracer.current_span()
    if span is None:
        return headers

    carrier: dict[str, str] = {}
    HTTPPropagator.inject(span.context, carrier)
    headers.update(carrier)
    return headers


def activate_trace_from_headers(headers: dict[str, Any] | None) -> None:
    if not headers or tracer is None or HTTPPropagator is None:
        return

    normalized: dict[str, str] = {}
    for key, value in headers.items():
        normalized[str(key)] = value.decode() if isinstance(value, bytes) else str(value)

    context = HTTPPropagator.extract(normalized)
    if getattr(context, "trace_id", None):
        tracer.context_provider.activate(context)
