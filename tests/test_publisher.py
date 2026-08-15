import json
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

from incident_platform.publisher import PUBLISH_TIMEOUT_SECONDS, PubSubTicketPublisher


# Publish内容と再試行を確認
def test_publish_ticket_sends_event_with_retry() -> None:
    client = MagicMock()
    client.topic_path.return_value = "projects/test-project/topics/incident-tickets"
    client.publish.return_value.result.return_value = "message-123"
    publisher = PubSubTicketPublisher("test-project", "incident-tickets", client)
    ticket_id = UUID("22222222-2222-2222-2222-222222222222")

    message_id = publisher.publish_ticket(
        ticket_id,
        datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )

    assert message_id == "message-123"
    client.topic_path.assert_called_once_with("test-project", "incident-tickets")
    args = client.publish.call_args.args
    kwargs = client.publish.call_args.kwargs
    event = json.loads(args[1])
    assert args[0] == "projects/test-project/topics/incident-tickets"
    assert event["schema_version"] == "1"
    assert UUID(event["event_id"])
    assert event["event_type"] == "ticket.created"
    assert event["ticket_id"] == str(ticket_id)
    assert event["created_at"] == "2026-08-15T12:00:00Z"
    assert kwargs["retry"] is publisher.retry
    assert kwargs["retry"].timeout == PUBLISH_TIMEOUT_SECONDS
    assert kwargs["timeout"] == PUBLISH_TIMEOUT_SECONDS
    client.publish.return_value.result.assert_called_once_with(timeout=PUBLISH_TIMEOUT_SECONDS)
