from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from incident_platform.db import Base
from incident_platform.schemas import TicketStatus


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
