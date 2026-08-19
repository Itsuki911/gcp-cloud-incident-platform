from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from incident_platform.attachment_service import build_object_name, validate_file
from incident_platform.attachment_storage import (
    AttachmentObjectNotFound,
    AttachmentStorageError,
    AttachmentStore,
    CloudStorageAttachmentStore,
)
from incident_platform.config import get_settings
from incident_platform.db import Base, SessionLocal, engine, get_session
from incident_platform.models import Attachment, Ticket
from incident_platform.publisher import PubSubTicketPublisher, TicketPublisher
from incident_platform.schemas import (
    AttachmentRead,
    AttachmentUploadCreate,
    AttachmentUploadCreated,
    TicketCreate,
    TicketCreated,
    TicketRead,
    TicketStatus,
)

settings = get_settings()
DatabaseSession = Annotated[Session, Depends(get_session)]
# データベースセッションを依存関係として注入するための型ヒント


# APIアプリを生成する
def create_app(
    database_engine: Engine = engine,
    session_factory: sessionmaker[Session] = SessionLocal,
    publisher: TicketPublisher | None = None,
    attachment_store: AttachmentStore | None = None,
) -> FastAPI:
    # DBテーブルを準備する
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Production schemas are managed by Alembic. Tests use an in-memory SQLite DB.
        if database_engine.dialect.name == "sqlite":
            Base.metadata.create_all(bind=database_engine)
        yield

    ticket_publisher = publisher or PubSubTicketPublisher(
        project=settings.google_cloud_project,
        topic=settings.pubsub_topic,
    )
    file_store = attachment_store or CloudStorageAttachmentStore(settings.attachment_bucket)
    application = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    application.state.session_factory = session_factory
    application.state.ticket_publisher = ticket_publisher
    application.state.attachment_store = file_store

    @application.get("/health", tags=["system"])
    # ヘルスチェックエンドポイント
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.app_env}

    # チケットを作成する
    @application.post(
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
        try:
            ticket_publisher.publish_ticket(ticket.id, ticket.created_at)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Ticket queued but Pub/Sub publish failed",
            ) from exc
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

    # 添付アップロードを開始する
    @application.post(
        "/tickets/{ticket_id}/attachments/uploads",
        response_model=AttachmentUploadCreated,
        status_code=status.HTTP_201_CREATED,
        tags=["attachments"],
    )
    def create_attachment_upload(
        ticket_id: UUID,
        payload: AttachmentUploadCreate,
        session: DatabaseSession,
    ) -> AttachmentUploadCreated:
        if session.get(Ticket, ticket_id) is None:
            raise HTTPException(status_code=404, detail="Ticket not found")
        try:
            filename, content_type = validate_file(payload.filename, payload.content_type)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        attachment = Attachment(
            id=uuid4(),
            ticket_id=ticket_id,
            bucket_name=file_store.bucket_name,
            object_name="",
            original_filename=filename,
            content_type=content_type,
            size=payload.size,
        )
        attachment.object_name = build_object_name(ticket_id, attachment.id, filename)
        try:
            upload_url = file_store.create_upload_session(
                attachment.object_name,
                content_type,
                payload.size,
                {"ticket-id": str(ticket_id), "original-filename": filename},
            )
        except AttachmentStorageError as exc:
            raise HTTPException(status_code=503, detail="Attachment storage unavailable") from exc
        session.add(attachment)
        session.commit()
        return AttachmentUploadCreated(
            id=attachment.id,
            upload_url=upload_url,
            content_type=content_type,
        )

    # 添付アップロードを完了する
    @application.post(
        "/tickets/{ticket_id}/attachments/{attachment_id}/complete",
        response_model=AttachmentRead,
        tags=["attachments"],
    )
    def complete_attachment_upload(
        ticket_id: UUID,
        attachment_id: UUID,
        session: DatabaseSession,
    ) -> AttachmentRead:
        attachment = _get_attachment(session, ticket_id, attachment_id)
        if attachment.generation is None:
            try:
                stored = file_store.get(attachment.object_name)
            except AttachmentObjectNotFound as exc:
                raise HTTPException(status_code=409, detail="Upload not completed") from exc
            except AttachmentStorageError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Attachment storage unavailable",
                ) from exc
            if stored.size != attachment.size or stored.content_type != attachment.content_type:
                raise HTTPException(status_code=409, detail="Uploaded file does not match")
            attachment.generation = stored.generation
            session.commit()
        return _attachment_read(attachment)

    # チケットの添付一覧を返す
    @application.get(
        "/tickets/{ticket_id}/attachments",
        response_model=list[AttachmentRead],
        tags=["attachments"],
    )
    def list_attachments(ticket_id: UUID, session: DatabaseSession) -> list[AttachmentRead]:
        if session.get(Ticket, ticket_id) is None:
            raise HTTPException(status_code=404, detail="Ticket not found")
        statement = (
            select(Attachment)
            .where(Attachment.ticket_id == ticket_id)
            .order_by(Attachment.created_at.asc())
        )
        return [_attachment_read(item) for item in session.scalars(statement)]

    # 添付ファイルを返す
    @application.get(
        "/tickets/{ticket_id}/attachments/{attachment_id}",
        tags=["attachments"],
    )
    def download_attachment(
        ticket_id: UUID,
        attachment_id: UUID,
        session: DatabaseSession,
    ) -> StreamingResponse:
        attachment = _get_attachment(session, ticket_id, attachment_id)
        if attachment.generation is None:
            raise HTTPException(status_code=409, detail="Upload not completed")
        try:
            stored = file_store.get(attachment.object_name)
        except AttachmentObjectNotFound as exc:
            raise HTTPException(status_code=404, detail="Attachment object not found") from exc
        except AttachmentStorageError as exc:
            raise HTTPException(status_code=503, detail="Attachment storage unavailable") from exc
        if stored.generation != attachment.generation:
            raise HTTPException(status_code=409, detail="Attachment generation changed")
        encoded_name = quote(attachment.original_filename)
        return StreamingResponse(
            file_store.download(attachment.object_name, attachment.generation),
            media_type=attachment.content_type,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
                "Content-Length": str(attachment.size),
            },
        )

    # 添付ファイルを削除する
    @application.delete(
        "/tickets/{ticket_id}/attachments/{attachment_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["attachments"],
    )
    def delete_attachment(
        ticket_id: UUID,
        attachment_id: UUID,
        session: DatabaseSession,
    ) -> Response:
        attachment = _get_attachment(session, ticket_id, attachment_id)
        try:
            file_store.delete(attachment.object_name, attachment.generation)
        except AttachmentStorageError as exc:
            raise HTTPException(status_code=503, detail="Attachment storage unavailable") from exc
        session.delete(attachment)
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return application


# 対象の添付情報を返す
def _get_attachment(session: Session, ticket_id: UUID, attachment_id: UUID) -> Attachment:
    statement = select(Attachment).where(
        Attachment.id == attachment_id,
        Attachment.ticket_id == ticket_id,
    )
    attachment = session.scalar(statement)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return attachment


# API用の添付情報を作る
def _attachment_read(attachment: Attachment) -> AttachmentRead:
    return AttachmentRead(
        id=attachment.id,
        ticket_id=attachment.ticket_id,
        original_filename=attachment.original_filename,
        content_type=attachment.content_type,
        size=attachment.size,
        status="ready" if attachment.generation is not None else "pending",
        created_at=attachment.created_at,
    )


app = create_app()
