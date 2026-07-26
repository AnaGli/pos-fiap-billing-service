from fastapi import FastAPI

from app.api.routes.billing import router as billing_router

app = FastAPI(title="Billing Service", version="0.1.0")
app.include_router(billing_router)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}
