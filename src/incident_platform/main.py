from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from incident_platform.config import get_settings
from incident_platform.db import Base, SessionLocal, engine, get_session
from incident_platform.models import Ticket
from incident_platform.schemas import TicketCreate, TicketCreated, TicketRead, TicketStatus

settings = get_settings()
DatabaseSession = Annotated[Session, Depends(get_session)]
# データベースセッションを依存関係として注入するための型ヒント


def create_app(
    database_engine: Engine = engine,
    session_factory: sessionmaker[Session] = SessionLocal,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        Base.metadata.create_all(bind=database_engine)
        yield

    application = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    application.state.session_factory = session_factory
    
    @application.get("/health", tags=["system"])
    # ヘルスチェックエンドポイント
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.app_env}

    @application.post(
            # チケット作成エンドポイント
        "/tickets",
        response_model=TicketCreated,
        status_code=status.HTTP_201_CREATED,
        tags=["tickets"],
    )
    def create_ticket(
        payload: TicketCreate,
        session: DatabaseSession,
    ) -> Ticket:
        ticket = Ticket(
            title=payload.title,
            raw_question=payload.raw_question,
            status=TicketStatus.queued.value,
        )
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        return ticket

    @application.get("/tickets", response_model=list[TicketRead], tags=["tickets"])
    # チケット一覧取得エンドポイント
    def list_tickets(session: DatabaseSession) -> list[Ticket]:
        statement = select(Ticket).order_by(Ticket.created_at.desc())
        return list(session.scalars(statement))

    @application.get("/tickets/{ticket_id}", response_model=TicketRead, tags=["tickets"])
    # チケット詳細取得エンドポイント
    def get_ticket(
        ticket_id: UUID,
        session: DatabaseSession,
    ) -> Ticket:
        ticket = session.get(Ticket, ticket_id)
        if ticket is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
        return ticket

    return application


app = create_app()
