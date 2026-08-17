from unittest.mock import MagicMock

from google.api_core.exceptions import AlreadyExists

from incident_platform.pubsub_emulator import create_subscription, create_topic


# Topic作成内容を確認
def test_create_topic() -> None:
    publisher = MagicMock()
    publisher.topic_path.return_value = "projects/local-project/topics/incident-tickets"

    topic_path = create_topic(publisher, "local-project", "incident-tickets")

    assert topic_path == "projects/local-project/topics/incident-tickets"
    publisher.create_topic.assert_called_once_with(
        request={"name": topic_path},
        retry=None,
        timeout=2,
    )


# Push購読の作成内容を確認
def test_create_subscription() -> None:
    subscriber = MagicMock()
    subscriber.subscription_path.return_value = (
        "projects/local-project/subscriptions/incident-tickets-worker"
    )
    topic_path = "projects/local-project/topics/incident-tickets"

    create_subscription(
        subscriber,
        "local-project",
        "incident-tickets-worker",
        topic_path,
        "http://worker:8081/pubsub/tickets",
    )

    subscriber.create_subscription.assert_called_once_with(
        request={
            "name": "projects/local-project/subscriptions/incident-tickets-worker",
            "topic": topic_path,
            "push_config": {"push_endpoint": "http://worker:8081/pubsub/tickets"},
        },
        retry=None,
        timeout=2,
    )


# 既存リソースを許可する
def test_existing_resources_are_allowed() -> None:
    publisher = MagicMock()
    publisher.topic_path.return_value = "projects/local-project/topics/incident-tickets"
    publisher.create_topic.side_effect = AlreadyExists("Topic exists")
    subscriber = MagicMock()
    subscriber.subscription_path.return_value = (
        "projects/local-project/subscriptions/incident-tickets-worker"
    )
    subscriber.create_subscription.side_effect = AlreadyExists("Subscription exists")

    topic_path = create_topic(publisher, "local-project", "incident-tickets")
    create_subscription(
        subscriber,
        "local-project",
        "incident-tickets-worker",
        topic_path,
        "http://worker:8081/pubsub/tickets",
    )
