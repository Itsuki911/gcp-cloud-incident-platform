import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from google.api_core.retry import Retry
from google.cloud import pubsub_v1

PUBLISH_TIMEOUT_SECONDS = 10.0


# Publish処理の契約
class TicketPublisher(Protocol):
    # チケット通知を送信する
    def publish_ticket(self, ticket_id: UUID, created_at: datetime) -> str: ...


# Pub/Subへ通知を送信
class PubSubTicketPublisher:
    # Publish先を初期化する
    def __init__(
        self,
        project: str,
        topic: str,
        client: pubsub_v1.PublisherClient | None = None,
    ) -> None:
        self.project = project
        self.topic = topic
        self.client = client
        self.retry = Retry(initial=1.0, maximum=4.0, multiplier=2.0, timeout=10.0)

    # Pub/Subクライアントを返す
    def get_client(self) -> pubsub_v1.PublisherClient:
        if self.client is None:
            self.client = pubsub_v1.PublisherClient()
        return self.client

    # UTC形式へ変換する
    def format_created_at(self, created_at: datetime) -> str:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return created_at.astimezone(UTC).isoformat().replace("+00:00", "Z")

    # チケット通知を送信する
    def publish_ticket(self, ticket_id: UUID, created_at: datetime) -> str:
        client = self.get_client()
        topic_path = client.topic_path(self.project, self.topic)
        event = {
            "schema_version": "1",
            "event_id": str(uuid4()),
            "event_type": "ticket.created",
            "ticket_id": str(ticket_id),
            "created_at": self.format_created_at(created_at),
        }
        data = json.dumps(event, separators=(",", ":")).encode()
        future = client.publish(
            topic_path,
            data,
            retry=self.retry,
            timeout=PUBLISH_TIMEOUT_SECONDS,
        )
        return future.result(timeout=PUBLISH_TIMEOUT_SECONDS)
