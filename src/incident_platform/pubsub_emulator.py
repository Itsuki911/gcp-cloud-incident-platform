import os
import time

from google.api_core.exceptions import AlreadyExists, GoogleAPICallError
from google.cloud import pubsub_v1

MAX_ATTEMPTS = 30


# Topicを作成する
def create_topic(
    publisher: pubsub_v1.PublisherClient,
    project_id: str,
    topic_id: str,
) -> str:
    topic_path = publisher.topic_path(project_id, topic_id)
    try:
        publisher.create_topic(request={"name": topic_path}, retry=None, timeout=2)
    except AlreadyExists:
        pass
    return topic_path


# Push購読を作成する
def create_subscription(
    subscriber: pubsub_v1.SubscriberClient,
    project_id: str,
    subscription_id: str,
    topic_path: str,
    push_endpoint: str,
) -> None:
    subscription_path = subscriber.subscription_path(project_id, subscription_id)
    try:
        subscriber.create_subscription(
            request={
                "name": subscription_path,
                "topic": topic_path,
                "push_config": {"push_endpoint": push_endpoint},
            },
            retry=None,
            timeout=2,
        )
    except AlreadyExists:
        pass


# Emulatorを初期化する
def initialize_emulator(
    project_id: str,
    topic_id: str,
    subscription_id: str,
    push_endpoint: str,
) -> None:
    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()

    for attempt in range(MAX_ATTEMPTS):
        try:
            topic_path = create_topic(publisher, project_id, topic_id)
            create_subscription(
                subscriber,
                project_id,
                subscription_id,
                topic_path,
                push_endpoint,
            )
            return
        except GoogleAPICallError:
            if attempt == MAX_ATTEMPTS - 1:
                raise
            time.sleep(1)


# 環境変数から初期化する
def main() -> None:
    initialize_emulator(
        project_id=os.getenv("PUBSUB_PROJECT_ID", "local-project"),
        topic_id=os.getenv("PUBSUB_TOPIC", "incident-tickets"),
        subscription_id=os.getenv("PUBSUB_SUBSCRIPTION", "incident-tickets-worker"),
        push_endpoint=os.getenv(
            "PUBSUB_PUSH_ENDPOINT",
            "http://worker:8081/pubsub/tickets",
        ),
    )


if __name__ == "__main__":
    main()
