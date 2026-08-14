from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# NonEmptyTextは、空白を削除し、最小長が1の文字列を表す型エイリアスです。
# カスタム型定義

class TicketStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class TicketCreate(BaseModel):
    #作成リクエスト用
    title: NonEmptyText
    raw_question: NonEmptyText


class TicketCreated(BaseModel):
    #作成直後のレスポンス用
    id: UUID
    status: TicketStatus

    model_config = ConfigDict(from_attributes=True)


class TicketRead(BaseModel):
    #詳細取得用
    id: UUID
    title: str
    category: str | None
    severity: str | None
    summary: str | None
    status: TicketStatus

    model_config = ConfigDict(from_attributes=True)
