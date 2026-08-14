from fastapi import FastAPI, Response, status

from incident_platform.config import get_settings

settings = get_settings()
app = FastAPI(title=f"{settings.app_name} Worker", version="0.1.0")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "worker"}


@app.post("/pubsub", status_code=status.HTTP_204_NO_CONTENT, tags=["pubsub"])
def receive_pubsub_message() -> Response:
    """Placeholder endpoint for a Pub/Sub push subscription."""

    return Response(status_code=status.HTTP_204_NO_CONTENT)
