import contextvars
import logging
import os
import uuid
from collections.abc import Mapping

from pythonjsonlogger import jsonlogger

_log_context: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar("log_context", default={})


def ensure_correlation_id() -> str:
    context = dict(_log_context.get())
    correlation_id = context.get("correlation_id")
    if correlation_id:
        return correlation_id
    correlation_id = str(uuid.uuid4())
    context["correlation_id"] = correlation_id
    _log_context.set(context)
    return correlation_id


def set_log_context(**kwargs: object) -> None:
    context = dict(_log_context.get())
    for key, value in kwargs.items():
        if value is None:
            continue
        context[key] = str(value)
    _log_context.set(context)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _log_context.get()
        for key, value in context.items():
            setattr(record, key, value)
        record.service = os.getenv("DD_SERVICE", "billing-service")
        record.env = os.getenv("DD_ENV", "dev")
        return True


class JsonLogFormatter(jsonlogger.JsonFormatter):
    def add_fields(
        self,
        log_record: dict[str, object],
        record: logging.LogRecord,
        message_dict: Mapping[str, object],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record.setdefault("level", record.levelname)
        log_record.setdefault("logger", record.name)


def setup_logging() -> None:
    root_logger = logging.getLogger()
    if any(getattr(handler, "_billing_json_logging", False) for handler in root_logger.handlers):
        return

    handler = logging.StreamHandler()
    handler._billing_json_logging = True  # type: ignore[attr-defined]
    handler.setFormatter(
        JsonLogFormatter(
            "%(asctime)s %(level)s %(name)s %(message)s %(service)s %(env)s %(correlation_id)s"
        )
    )
    handler.addFilter(ContextFilter())

    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
