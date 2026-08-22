from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from incident_platform.db import Base
from incident_platform.schemas import EventProcessingStatus, TicketStatus


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(255))
    raw_question: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=TicketStatus.queued.value)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


# Event処理履歴を保存する
class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    ticket_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tickets.id"), index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default=EventProcessingStatus.processing.value,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    first_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


# 添付情報を保存する
class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    ticket_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tickets.id"), index=True)
    bucket_name: Mapped[str] = mapped_column(String(255))
    object_name: Mapped[str] = mapped_column(String(1024), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(BigInteger)
    generation: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
