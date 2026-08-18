from unittest.mock import MagicMock

from incident_platform.attachment_storage import CloudStorageAttachmentStore


# URL発行の上書き防止を確認する
def test_storage_creates_safe_upload_session() -> None:
    client = MagicMock()
    blob = client.bucket.return_value.blob.return_value
    blob.create_resumable_upload_session.return_value = "https://upload.test/session"
    store = CloudStorageAttachmentStore("test-bucket")
    store._client = client

    result = store.create_upload_session(
        "tickets/id/file.pdf",
        "application/pdf",
        10,
        {"ticket-id": "id"},
    )

    assert result == "https://upload.test/session"
    assert blob.metadata == {"ticket-id": "id"}
    blob.create_resumable_upload_session.assert_called_once_with(
        content_type="application/pdf",
        size=10,
        if_generation_match=0,
    )


# 世代一致で削除することを確認する
def test_storage_deletes_matching_generation() -> None:
    client = MagicMock()
    blob = client.bucket.return_value.blob.return_value
    store = CloudStorageAttachmentStore("test-bucket")
    store._client = client

    store.delete("tickets/id/file.pdf", 7)

    client.bucket.return_value.blob.assert_called_once_with(
        "tickets/id/file.pdf",
        generation=7,
    )
    blob.delete.assert_called_once_with(if_generation_match=7)
