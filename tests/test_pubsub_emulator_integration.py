import os
import time
from uuid import uuid4

import httpx
import pytest

RUN_INTEGRATION = os.getenv("RUN_PUBSUB_EMULATOR_TEST") == "1"


# Composeの処理全体を確認
@pytest.mark.skipif(not RUN_INTEGRATION, reason="Pub/Sub Emulator is not running")
def test_compose_ticket_flow() -> None:
    response = httpx.post(
        "http://localhost:8080/tickets",
        json={
            "title": f"Emulator test {uuid4()}",
            "raw_question": "ローカルの非同期処理を確認します。",
        },
        timeout=10,
    )

    assert response.status_code == 201
    ticket_id = response.json()["id"]

    for _ in range(20):
        ticket = httpx.get(f"http://localhost:8080/tickets/{ticket_id}", timeout=5)
        assert ticket.status_code == 200
        if ticket.json()["status"] == "completed":
            break
        time.sleep(1)

    result = ticket.json()
    assert result["status"] == "completed"
    assert result["category"] == "other"
    assert result["severity"] == "low"
    assert result["summary"] == "ローカル環境の固定解析結果です。"
