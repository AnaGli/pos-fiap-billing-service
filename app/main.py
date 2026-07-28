import time
from contextlib import suppress

from ddtrace import patch_all
from ddtrace.contrib.asgi import TraceMiddleware
from fastapi import FastAPI, Request

from app.api.routes.billing import router as billing_router
from app.core.logging_config import ensure_correlation_id, set_log_context, setup_logging
from app.core.tracing import configure_tracing

with suppress(ImportError):
    patch_all()

setup_logging()
configure_tracing()
app = FastAPI(title="Billing Service", version="0.1.0")
app.add_middleware(TraceMiddleware)
app.include_router(billing_router)


@app.middleware("http")
async def add_request_context(request: Request, call_next):
    correlation_id = request.headers.get("x-correlation-id") or ensure_correlation_id()
    set_log_context(
        correlation_id=correlation_id,
        business_operation="billing_http_request",
        path=request.url.path,
        method=request.method,
    )
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["x-correlation-id"] = correlation_id
    set_log_context(
        http_status=response.status_code,
        duration_ms=int((time.perf_counter() - start) * 1000),
    )
    return response


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}
