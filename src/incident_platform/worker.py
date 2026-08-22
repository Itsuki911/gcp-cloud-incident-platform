import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from incident_platform.ai_worker import GeminiTicketAnalyzer, LocalTicketAnalyzer, TicketAnalyzer
from incident_platform.config import get_settings
from incident_platform.db import Base, SessionLocal, engine, get_session
from incident_platform.models import ProcessedEvent, Ticket
from incident_platform.schemas import EventProcessingStatus, TicketStatus

settings = get_settings()
DatabaseSession = Annotated[Session, Depends(get_session)]


# Pub/Subメッセージを表す
class PubSubMessage(BaseModel):
    data: str


# Push通知全体を表す
class PubSubPush(BaseModel):
    message: PubSubMessage
    subscription: str | None = None

    model_config = ConfigDict(extra="ignore")


# チケット通知を表す
class TicketEvent(BaseModel):
    schema_version: str
    event_id: UUID
    event_type: str
    ticket_id: UUID
    created_at: str


# 通知データを復号する
def decode_event(data: str) -> TicketEvent:
    decoded = base64.b64decode(data, validate=True)
    return TicketEvent.model_validate(json.loads(decoded))


# Workerアプリを生成する
def create_worker_app(
    database_engine: Engine = engine,
    session_factory: sessionmaker[Session] = SessionLocal,
    analyzer: TicketAnalyzer | None = None,
) -> FastAPI:
    # DBテーブルを準備する
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Production schemas are managed by Alembic. Tests use an in-memory SQLite DB.
        if database_engine.dialect.name == "sqlite":
            Base.metadata.create_all(bind=database_engine)
        yield

    # 実行環境の分析処理を選ぶ
    ticket_analyzer = analyzer or (
        LocalTicketAnalyzer()
        if settings.use_local_analyzer
        else GeminiTicketAnalyzer(
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            model=settings.gemini_model,
        )
    )
    application = FastAPI(title="Incident AI Worker", version="0.1.0", lifespan=lifespan)
    application.state.session_factory = session_factory

    # Worker稼働状態を返す
    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.app_env}

    # チケット通知を処理する
    @application.post("/pubsub/tickets", status_code=status.HTTP_204_NO_CONTENT)
    def process_ticket(payload: PubSubPush, session: DatabaseSession) -> Response:
        try:
            event = decode_event(payload.message.data)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid Pub/Sub message") from exc

        if event.schema_version != "1" or event.event_type != "ticket.created":
            raise HTTPException(status_code=400, detail="Unsupported ticket event")

        ticket = session.scalar(
            select(Ticket).where(Ticket.id == event.ticket_id).with_for_update()
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="Ticket not found")

        processed_event = session.get(ProcessedEvent, event.event_id)
        if processed_event is not None and (
            processed_event.ticket_id != event.ticket_id
            or processed_event.event_type != event.event_type
        ):
            raise HTTPException(status_code=400, detail="Conflicting event identifier")
        if (
            processed_event is not None
            and processed_event.status == EventProcessingStatus.completed.value
        ):
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        received_at = datetime.now(UTC)
        if processed_event is None:
            processed_event = ProcessedEvent(
                event_id=event.event_id,
                event_type=event.event_type,
                ticket_id=event.ticket_id,
                status=EventProcessingStatus.processing.value,
                attempt_count=1,
                first_received_at=received_at,
            )
            session.add(processed_event)
        else:
            processed_event.status = EventProcessingStatus.processing.value
            processed_event.attempt_count += 1
            processed_event.last_error = None

        if ticket.status == TicketStatus.completed.value:
            processed_event.status = EventProcessingStatus.completed.value
            processed_event.completed_at = received_at
            session.commit()
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=400,
                detail="Conflicting event identifier",
            ) from exc

        try:
            with session.begin_nested():
                ticket.status = TicketStatus.processing.value
                session.flush()
                result = ticket_analyzer.analyze(ticket.title, ticket.raw_question)
                ticket.category = result.category.value
                ticket.severity = result.severity.value
                ticket.summary = result.summary
                ticket.status = TicketStatus.completed.value
                processed_event.status = EventProcessingStatus.completed.value
                processed_event.completed_at = datetime.now(UTC)
        except Exception as exc:
            processed_event.status = EventProcessingStatus.failed.value
            processed_event.last_error = type(exc).__name__
            session.commit()
            raise HTTPException(status_code=500, detail="AI processing failed") from exc

        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return application


app = create_worker_app()
