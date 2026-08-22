import base64
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from incident_platform.ai_worker import (
    SYSTEM_PROMPT,
    Category,
    GeminiTicketAnalyzer,
    LocalTicketAnalyzer,
    Severity,
    TicketAnalysis,
)
from incident_platform.models import ProcessedEvent, Ticket
from incident_platform.schemas import EventProcessingStatus, TicketStatus
from incident_platform.worker import create_worker_app


# 固定のAI結果を返す
class StubAnalyzer:
    # 呼び出し回数を初期化
    def __init__(self) -> None:
        self.calls = 0

    # 固定結果を返す
    def analyze(self, title: str, raw_question: str) -> TicketAnalysis:
        self.calls += 1
        return TicketAnalysis(
            category=Category.authentication,
            severity=Severity.high,
            summary="ログイン機能でエラーが発生しています。",
        )


# AI障害を再現する
class FailingAnalyzer:
    # AI障害を発生させる
    def analyze(self, title: str, raw_question: str) -> TicketAnalysis:
        raise RuntimeError("Vertex AI unavailable")


# Workerのテスト環境を作る
@pytest.fixture
def worker_client() -> Iterator[tuple[TestClient, sessionmaker[Session], StubAnalyzer]]:
    database_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(
        bind=database_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    analyzer = StubAnalyzer()
    application = create_worker_app(database_engine, session_factory, analyzer)

    with TestClient(application) as client:
        yield client, session_factory, analyzer

    database_engine.dispose()


# Push通知本文を作る
def push_body(ticket_id: UUID, event_id: UUID | None = None) -> dict[str, object]:
    event = {
        "schema_version": "1",
        "event_id": str(event_id or uuid4()),
        "event_type": "ticket.created",
        "ticket_id": str(ticket_id),
        "created_at": datetime.now(UTC).isoformat(),
    }
    data = base64.b64encode(json.dumps(event).encode()).decode()
    return {"message": {"data": data}, "subscription": "incident-tickets-worker"}


# チケットをDBへ登録する
def create_ticket(session_factory: sessionmaker[Session]) -> Ticket:
    with session_factory() as session:
        ticket = Ticket(title="ログイン障害", raw_question="全員がログインできません。")
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        return ticket


# AI結果が保存されることを確認
def test_worker_updates_ticket(
    worker_client: tuple[TestClient, sessionmaker[Session], StubAnalyzer],
) -> None:
    client, session_factory, analyzer = worker_client
    ticket = create_ticket(session_factory)

    response = client.post("/pubsub/tickets", json=push_body(ticket.id))

    assert response.status_code == 204
    assert analyzer.calls == 1
    with session_factory() as session:
        saved = session.get(Ticket, ticket.id)
        assert saved is not None
        assert saved.category == "authentication"
        assert saved.severity == "high"
        assert saved.summary == "ログイン機能でエラーが発生しています。"
        assert saved.status == TicketStatus.completed.value
        processed_event = session.scalar(select(ProcessedEvent))
        assert processed_event is not None
        assert processed_event.status == EventProcessingStatus.completed.value
        assert processed_event.attempt_count == 1
        assert processed_event.completed_at is not None
        assert processed_event.last_error is None


# 再配信が重複処理されないことを確認
def test_worker_acks_completed_ticket(
    worker_client: tuple[TestClient, sessionmaker[Session], StubAnalyzer],
) -> None:
    client, session_factory, analyzer = worker_client
    ticket = create_ticket(session_factory)
    body = push_body(ticket.id)

    assert client.post("/pubsub/tickets", json=body).status_code == 204
    assert client.post("/pubsub/tickets", json=body).status_code == 204
    assert analyzer.calls == 1
    with session_factory() as session:
        processed_event = session.scalar(select(ProcessedEvent))
        assert processed_event is not None
        assert processed_event.attempt_count == 1


# AI障害時の再試行応答を確認
def test_worker_returns_500_and_rolls_back() -> None:
    database_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(
        bind=database_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    event_id = uuid4()
    body: dict[str, object]
    application = create_worker_app(database_engine, session_factory, FailingAnalyzer())

    with TestClient(application) as client:
        ticket = create_ticket(session_factory)
        body = push_body(ticket.id, event_id)
        response = client.post("/pubsub/tickets", json=body)

    assert response.status_code == 500
    with session_factory() as session:
        saved = session.get(Ticket, ticket.id)
        assert saved is not None
        assert saved.status == TicketStatus.queued.value
        processed_event = session.get(ProcessedEvent, event_id)
        assert processed_event is not None
        assert processed_event.status == EventProcessingStatus.failed.value
        assert processed_event.attempt_count == 1
        assert processed_event.last_error == "RuntimeError"

    retry_analyzer = StubAnalyzer()
    retry_application = create_worker_app(database_engine, session_factory, retry_analyzer)
    with TestClient(retry_application) as client:
        response = client.post("/pubsub/tickets", json=body)

    assert response.status_code == 204
    assert retry_analyzer.calls == 1
    with session_factory() as session:
        processed_event = session.get(ProcessedEvent, event_id)
        assert processed_event is not None
        assert processed_event.status == EventProcessingStatus.completed.value
        assert processed_event.attempt_count == 2
        assert processed_event.completed_at is not None
        assert processed_event.last_error is None

    database_engine.dispose()


# Event ID衝突を拒否する
def test_worker_rejects_conflicting_event_id(
    worker_client: tuple[TestClient, sessionmaker[Session], StubAnalyzer],
) -> None:
    client, session_factory, analyzer = worker_client
    first_ticket = create_ticket(session_factory)
    second_ticket = create_ticket(session_factory)
    event_id = uuid4()

    first_response = client.post(
        "/pubsub/tickets",
        json=push_body(first_ticket.id, event_id),
    )
    second_response = client.post(
        "/pubsub/tickets",
        json=push_body(second_ticket.id, event_id),
    )

    assert first_response.status_code == 204
    assert second_response.status_code == 400
    assert second_response.json() == {"detail": "Conflicting event identifier"}
    assert analyzer.calls == 1
    with session_factory() as session:
        second_saved = session.get(Ticket, second_ticket.id)
        assert second_saved is not None
        assert second_saved.status == TicketStatus.queued.value


# 不正通知を拒否することを確認
def test_worker_rejects_invalid_message(
    worker_client: tuple[TestClient, sessionmaker[Session], StubAnalyzer],
) -> None:
    client, _, _ = worker_client

    response = client.post("/pubsub/tickets", json={"message": {"data": "not-base64"}})

    assert response.status_code == 400


# Gemini呼び出し設定を確認
def test_gemini_analyzer_uses_vertex_client() -> None:
    expected = TicketAnalysis(
        category=Category.database,
        severity=Severity.medium,
        summary="データベース接続に遅延があります。",
    )
    client = MagicMock()
    client.models.generate_content.return_value.parsed = expected
    analyzer = GeminiTicketAnalyzer("test-project", "global", "gemini-2.5-flash-lite", client)

    result = analyzer.analyze("DB遅延", "接続に時間がかかります。")

    assert result == expected
    request = client.models.generate_content.call_args.kwargs
    assert request["model"] == "gemini-2.5-flash-lite"
    assert request["contents"] == "タイトル: DB遅延\n問い合わせ: 接続に時間がかかります。"
    assert request["config"].system_instruction == SYSTEM_PROMPT
    assert request["config"].response_schema == TicketAnalysis


# ローカル固定分析を確認
def test_local_analyzer_returns_fixed_result() -> None:
    analyzer = LocalTicketAnalyzer()

    result = analyzer.analyze("接続確認", "ローカル処理を確認します。")

    assert result.category == Category.other
    assert result.severity == Severity.low
    assert result.summary == "ローカル環境の固定解析結果です。"
