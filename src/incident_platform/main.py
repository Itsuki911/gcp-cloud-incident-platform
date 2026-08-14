from fastapi import FastAPI

from incident_platform.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Return the API process health."""

    return {"status": "ok", "environment": settings.app_env}
