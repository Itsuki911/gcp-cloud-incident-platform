from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# NonEmptyTextは、空白を削除し、最小長が1の文字列を表す型エイリアスです。
# カスタム型定義


class TicketStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


# Event処理状態を表す
class EventProcessingStatus(StrEnum):
    processing = "processing"
    completed = "completed"
    failed = "failed"


class TicketCreate(BaseModel):
    # 作成リクエスト用
    title: NonEmptyText
    raw_question: NonEmptyText


class TicketCreated(BaseModel):
    # 作成直後のレスポンス用
    id: UUID
    status: TicketStatus

    model_config = ConfigDict(from_attributes=True)


class TicketRead(BaseModel):
    # 詳細取得用
    id: UUID
    title: str
    category: str | None
    severity: str | None
    summary: str | None
    status: TicketStatus

    model_config = ConfigDict(from_attributes=True)


# アップロード情報を受け取る
class AttachmentUploadCreate(BaseModel):
    filename: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    content_type: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    size: int = Field(gt=0, le=500 * 1024 * 1024)


# アップロード先を返す
class AttachmentUploadCreated(BaseModel):
    id: UUID
    upload_url: str
    method: Literal["PUT"] = "PUT"
    content_type: str


# 添付情報を返す
class AttachmentRead(BaseModel):
    id: UUID
    ticket_id: UUID
    original_filename: str
    content_type: str
    size: int
    status: Literal["pending", "ready"]
    created_at: datetime
