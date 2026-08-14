from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from incident_platform.models import Ticket


def test_health(client_and_session: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, _ = client_and_session

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "development"}


def test_create_and_get_ticket(
    client_and_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = client_and_session

    create_response = client.post(
        "/tickets",
        json={"title": " ログインエラー ", "raw_question": " 500エラーが発生します。 "},
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert UUID(created["id"])
    assert created["status"] == "queued"

    with session_factory() as session:
        ticket = session.get(Ticket, UUID(created["id"]))
        assert ticket is not None
        assert ticket.title == "ログインエラー"
        assert ticket.raw_question == "500エラーが発生します。"

    get_response = client.get(f"/tickets/{created['id']}")

    assert get_response.status_code == 200
    assert get_response.json() == {
        "id": created["id"],
        "title": "ログインエラー",
        "category": None,
        "severity": None,
        "summary": None,
        "status": "queued",
    }


def test_list_tickets_newest_first(
    client_and_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_and_session
    client.post("/tickets", json={"title": "first", "raw_question": "first question"})
    client.post("/tickets", json={"title": "second", "raw_question": "second question"})

    response = client.get("/tickets")

    assert response.status_code == 200
    assert [ticket["title"] for ticket in response.json()] == ["second", "first"]


def test_get_unknown_ticket_returns_404(
    client_and_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_and_session

    response = client.get(f"/tickets/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket not found"}


def test_create_ticket_rejects_blank_fields(
    client_and_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_and_session

    response = client.post("/tickets", json={"title": "   ", "raw_question": ""})

    assert response.status_code == 422
