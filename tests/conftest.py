from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from incident_platform.main import create_app


@pytest.fixture
def client_and_session() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app = create_app(database_engine=engine, session_factory=session_factory)

    with TestClient(app) as client:
        yield client, session_factory

    engine.dispose()
