from collections.abc import Iterator
from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from incident_platform.attachment_service import ALLOWED_FILE_TYPES, validate_file
from incident_platform.attachment_storage import AttachmentObjectNotFound, StoredAttachment
from incident_platform.main import create_app
from incident_platform.models import Attachment


# Publish処理を代替する
class StubPublisher:
    # Publish成功を返す
    def publish_ticket(self, ticket_id: UUID, created_at: datetime) -> str:
        return "test-message-id"


# 添付保存処理を代替する
class FakeAttachmentStore:
    bucket_name = "test-attachments"

    # 保存状態を初期化する
    def __init__(self) -> None:
        self.sessions: dict[str, tuple[str, int, dict[str, str]]] = {}
        self.objects: dict[str, tuple[bytes, str, int]] = {}

    # テスト用URLを返す
    def create_upload_session(
        self,
        object_name: str,
        content_type: str,
        size: int,
        metadata: dict[str, str],
    ) -> str:
        self.sessions[object_name] = (content_type, size, metadata)
        return f"https://upload.test/{quote(object_name)}"

    # 保存済み情報を返す
    def get(self, object_name: str) -> StoredAttachment:
        if object_name not in self.objects:
            raise AttachmentObjectNotFound
        data, content_type, generation = self.objects[object_name]
        return StoredAttachment(len(data), content_type, generation)

    # 保存データを分割する
    def download(self, object_name: str, generation: int) -> Iterator[bytes]:
        data, _, stored_generation = self.objects[object_name]
        if generation != stored_generation:
            raise AttachmentObjectNotFound
        yield data

    # 保存データを削除する
    def delete(self, object_name: str, generation: int | None = None) -> None:
        self.objects.pop(object_name, None)

    # アップロード完了を再現する
    def finish(self, object_name: str, data: bytes, content_type: str) -> None:
        self.objects[object_name] = (data, content_type, 7)


# 添付テスト環境を作る
@pytest.fixture
def attachment_client() -> Iterator[tuple[TestClient, sessionmaker[Session], FakeAttachmentStore]]:
    database_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=database_engine, expire_on_commit=False)
    store = FakeAttachmentStore()
    application = create_app(
        database_engine,
        session_factory,
        StubPublisher(),
        store,
    )
    with TestClient(application) as client:
        yield client, session_factory, store
    database_engine.dispose()


# テスト用チケットを作る
def create_ticket(client: TestClient) -> str:
    response = client.post(
        "/tickets",
        json={"title": "添付確認", "raw_question": "ログを確認してください。"},
    )
    return response.json()["id"]


# アップロードを開始する
def start_upload(client: TestClient, ticket_id: str, **overrides: Any) -> dict[str, Any]:
    payload = {"filename": "error.log", "content_type": "text/plain", "size": 5}
    payload.update(overrides)
    response = client.post(f"/tickets/{ticket_id}/attachments/uploads", json=payload)
    assert response.status_code == 201
    return response.json()


# DB上の添付を取得する
def get_saved_attachment(session_factory: sessionmaker[Session], attachment_id: str) -> Attachment:
    with session_factory() as session:
        attachment = session.get(Attachment, UUID(attachment_id))
        assert attachment is not None
        session.expunge(attachment)
        return attachment


# URL発行とDB保存を確認する
def test_create_upload_session(
    attachment_client: tuple[TestClient, sessionmaker[Session], FakeAttachmentStore],
) -> None:
    client, session_factory, store = attachment_client
    ticket_id = create_ticket(client)

    created = start_upload(client, ticket_id, filename="../error.log")

    attachment = get_saved_attachment(session_factory, created["id"])
    assert created["method"] == "PUT"
    assert created["content_type"] == "text/plain"
    assert attachment.original_filename == "error.log"
    assert attachment.object_name.startswith(f"tickets/{ticket_id}/{created['id']}-")
    assert store.sessions[attachment.object_name] == (
        "text/plain",
        5,
        {"ticket-id": ticket_id, "original-filename": "error.log"},
    )


# ZIPと上限容量を許可する
def test_accepts_zip_at_size_limit(
    attachment_client: tuple[TestClient, sessionmaker[Session], FakeAttachmentStore],
) -> None:
    client, _, _ = attachment_client
    ticket_id = create_ticket(client)

    response = client.post(
        f"/tickets/{ticket_id}/attachments/uploads",
        json={
            "filename": "logs.zip",
            "content_type": "application/zip",
            "size": 500 * 1024 * 1024,
        },
    )

    assert response.status_code == 201


# 許可形式の組合せを確認する
@pytest.mark.parametrize(
    ("extension", "content_type"),
    [(extension, next(iter(types))) for extension, types in ALLOWED_FILE_TYPES.items()],
)
def test_accepts_allowed_file_types(extension: str, content_type: str) -> None:
    filename, media_type = validate_file(f"sample{extension}", content_type)

    assert filename == f"sample{extension}"
    assert media_type == content_type


# 不正形式と容量超過を拒否する
@pytest.mark.parametrize(
    "payload",
    [
        {"filename": "run.exe", "content_type": "application/octet-stream", "size": 1},
        {"filename": "fake.pdf", "content_type": "image/png", "size": 1},
        {"filename": "large.zip", "content_type": "application/zip", "size": 524288001},
    ],
)
def test_rejects_invalid_upload(
    attachment_client: tuple[TestClient, sessionmaker[Session], FakeAttachmentStore],
    payload: dict[str, Any],
) -> None:
    client, _, _ = attachment_client
    ticket_id = create_ticket(client)

    response = client.post(f"/tickets/{ticket_id}/attachments/uploads", json=payload)

    assert response.status_code == 422


# 未完了アップロードを拒否する
def test_complete_requires_uploaded_object(
    attachment_client: tuple[TestClient, sessionmaker[Session], FakeAttachmentStore],
) -> None:
    client, _, _ = attachment_client
    ticket_id = create_ticket(client)
    created = start_upload(client, ticket_id)

    response = client.post(f"/tickets/{ticket_id}/attachments/{created['id']}/complete")

    assert response.status_code == 409
    assert response.json() == {"detail": "Upload not completed"}


# 不一致のアップロードを拒否する
def test_complete_rejects_size_mismatch(
    attachment_client: tuple[TestClient, sessionmaker[Session], FakeAttachmentStore],
) -> None:
    client, session_factory, store = attachment_client
    ticket_id = create_ticket(client)
    created = start_upload(client, ticket_id)
    attachment = get_saved_attachment(session_factory, created["id"])
    store.finish(attachment.object_name, b"x", "text/plain")

    response = client.post(f"/tickets/{ticket_id}/attachments/{created['id']}/complete")

    assert response.status_code == 409
    assert response.json() == {"detail": "Uploaded file does not match"}


# 完了後の一覧を確認する
def test_complete_and_list_attachment(
    attachment_client: tuple[TestClient, sessionmaker[Session], FakeAttachmentStore],
) -> None:
    client, session_factory, store = attachment_client
    ticket_id = create_ticket(client)
    created = start_upload(client, ticket_id)
    attachment = get_saved_attachment(session_factory, created["id"])
    store.finish(attachment.object_name, b"error", "text/plain")

    complete_response = client.post(f"/tickets/{ticket_id}/attachments/{created['id']}/complete")
    list_response = client.get(f"/tickets/{ticket_id}/attachments")

    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "ready"
    assert list_response.status_code == 200
    assert list_response.json()[0]["original_filename"] == "error.log"
    assert list_response.json()[0]["status"] == "ready"


# 添付をストリーム取得する
def test_download_attachment(
    attachment_client: tuple[TestClient, sessionmaker[Session], FakeAttachmentStore],
) -> None:
    client, session_factory, store = attachment_client
    ticket_id = create_ticket(client)
    created = start_upload(client, ticket_id)
    attachment = get_saved_attachment(session_factory, created["id"])
    store.finish(attachment.object_name, b"error", "text/plain")
    client.post(f"/tickets/{ticket_id}/attachments/{created['id']}/complete")

    response = client.get(f"/tickets/{ticket_id}/attachments/{created['id']}")

    assert response.status_code == 200
    assert response.content == b"error"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert "error.log" in response.headers["content-disposition"]


# 添付とDB情報を削除する
def test_delete_attachment(
    attachment_client: tuple[TestClient, sessionmaker[Session], FakeAttachmentStore],
) -> None:
    client, session_factory, store = attachment_client
    ticket_id = create_ticket(client)
    created = start_upload(client, ticket_id)
    attachment = get_saved_attachment(session_factory, created["id"])
    store.finish(attachment.object_name, b"error", "text/plain")
    client.post(f"/tickets/{ticket_id}/attachments/{created['id']}/complete")

    response = client.delete(f"/tickets/{ticket_id}/attachments/{created['id']}")

    assert response.status_code == 204
    assert attachment.object_name not in store.objects
    with session_factory() as session:
        assert session.get(Attachment, UUID(created["id"])) is None


# 別チケットからの取得を拒否する
def test_rejects_other_ticket_attachment(
    attachment_client: tuple[TestClient, sessionmaker[Session], FakeAttachmentStore],
) -> None:
    client, _, _ = attachment_client
    ticket_id = create_ticket(client)
    other_ticket_id = create_ticket(client)
    created = start_upload(client, ticket_id)

    response = client.delete(f"/tickets/{other_ticket_id}/attachments/{created['id']}")

    assert response.status_code == 404
