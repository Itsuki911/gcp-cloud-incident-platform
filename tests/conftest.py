from collections.abc import Iterator
from datetime import datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from incident_platform.main import create_app


# Publish結果を記録する
class StubPublisher:
    # 記録領域を初期化する
    def __init__(self) -> None:
        self.ticket_ids: list[UUID] = []
        self.error: Exception | None = None

    # Publish結果を記録する
    def publish_ticket(self, ticket_id: UUID, created_at: datetime) -> str:
        self.ticket_ids.append(ticket_id)
        if self.error is not None:
            raise self.error
        return "test-message-id"


@pytest.fixture
def client_and_session() -> Iterator[
    tuple[TestClient, sessionmaker[Session], StubPublisher]
]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    publisher = StubPublisher()
    app = create_app(database_engine=engine, session_factory=session_factory, publisher=publisher)

    with TestClient(app) as client:
        yield client, session_factory, publisher

    engine.dispose()
