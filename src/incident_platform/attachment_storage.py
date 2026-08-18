from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from google.auth.exceptions import GoogleAuthError
from google.cloud import storage
from google.cloud.exceptions import GoogleCloudError, NotFound


# 保存先の障害を表す
class AttachmentStorageError(Exception):
    pass


# 未保存の添付を表す
class AttachmentObjectNotFound(AttachmentStorageError):
    pass


# 保存済み情報を表す
@dataclass(frozen=True)
class StoredAttachment:
    size: int
    content_type: str
    generation: int


# 添付保存処理を定義する
class AttachmentStore(Protocol):
    bucket_name: str

    # アップロード先を作る
    def create_upload_session(
        self,
        object_name: str,
        content_type: str,
        size: int,
        metadata: dict[str, str],
    ) -> str: ...

    # 保存済み情報を取得する
    def get(self, object_name: str) -> StoredAttachment: ...

    # 添付データを読み出す
    def download(self, object_name: str, generation: int) -> Iterator[bytes]: ...

    # 添付データを削除する
    def delete(self, object_name: str, generation: int | None = None) -> None: ...


# Cloud Storageを操作する
class CloudStorageAttachmentStore:
    # Bucket情報を保持する
    def __init__(self, bucket_name: str) -> None:
        self.bucket_name = bucket_name
        self._client: storage.Client | None = None

    # Storageクライアントを返す
    def _get_client(self) -> storage.Client:
        if self._client is None:
            self._client = storage.Client()
        return self._client

    # 対象Objectを生成する
    def _blob(self, object_name: str, generation: int | None = None) -> storage.Blob:
        bucket = self._get_client().bucket(self.bucket_name)
        return bucket.blob(object_name, generation=generation)

    # 再開可能URLを発行する
    def create_upload_session(
        self,
        object_name: str,
        content_type: str,
        size: int,
        metadata: dict[str, str],
    ) -> str:
        try:
            blob = self._blob(object_name)
            blob.metadata = metadata
            return blob.create_resumable_upload_session(
                content_type=content_type,
                size=size,
                if_generation_match=0,
            )
        except (GoogleAuthError, GoogleCloudError) as exc:
            raise AttachmentStorageError from exc

    # Object情報を取得する
    def get(self, object_name: str) -> StoredAttachment:
        try:
            blob = self._blob(object_name)
            blob.reload()
        except NotFound as exc:
            raise AttachmentObjectNotFound from exc
        except (GoogleAuthError, GoogleCloudError) as exc:
            raise AttachmentStorageError from exc
        return StoredAttachment(
            size=int(blob.size or 0),
            content_type=blob.content_type or "application/octet-stream",
            generation=int(blob.generation or 0),
        )

    # Objectを分割取得する
    def download(self, object_name: str, generation: int) -> Iterator[bytes]:
        try:
            with self._blob(object_name, generation).open("rb") as file:
                while chunk := file.read(1024 * 1024):
                    yield chunk
        except NotFound as exc:
            raise AttachmentObjectNotFound from exc
        except (GoogleAuthError, GoogleCloudError) as exc:
            raise AttachmentStorageError from exc

    # Objectを安全に削除する
    def delete(self, object_name: str, generation: int | None = None) -> None:
        try:
            self._blob(object_name, generation).delete(if_generation_match=generation)
        except NotFound:
            return
        except (GoogleAuthError, GoogleCloudError) as exc:
            raise AttachmentStorageError from exc
