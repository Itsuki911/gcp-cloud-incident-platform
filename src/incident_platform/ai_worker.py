from enum import StrEnum
from typing import Annotated, Protocol

from google import genai
from google.genai import types
from pydantic import BaseModel, StringConstraints

SYSTEM_PROMPT = """あなたはインシデント受付の一次判定AIです。
問い合わせの事実だけを使い、カテゴリ、重大度、要約を日本語で返してください。
カテゴリは authentication, availability, performance, networking, database,
security, billing, other のいずれかにしてください。
重大度は critical, high, medium, low のいずれかにしてください。
critical は全体停止や重大な安全・情報漏えい、high は主要機能停止、
medium は一部機能の影響、low は軽微な問題や一般質問に使用してください。
判断材料が不足する場合は推測せず、最も控えめな重大度を選んでください。
要約は原因を断定せず、100文字以内で簡潔に記述してください。"""


# 問い合わせ分類を表す
class Category(StrEnum):
    authentication = "authentication"
    availability = "availability"
    performance = "performance"
    networking = "networking"
    database = "database"
    security = "security"
    billing = "billing"
    other = "other"


# 重大度を表す
class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


# AIの判定結果を表す
class TicketAnalysis(BaseModel):
    category: Category
    severity: Severity
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


# AI分析処理の契約
class TicketAnalyzer(Protocol):
    # 問い合わせを分析する
    def analyze(self, title: str, raw_question: str) -> TicketAnalysis: ...


# ローカル用の固定分析
class LocalTicketAnalyzer:
    # 固定の分析結果を返す
    def analyze(self, title: str, raw_question: str) -> TicketAnalysis:
        return TicketAnalysis(
            category=Category.other,
            severity=Severity.low,
            summary="ローカル環境の固定解析結果です。",
        )


# Geminiで問い合わせを分析
class GeminiTicketAnalyzer:
    # Vertex AI接続を初期化
    def __init__(
        self,
        project: str,
        location: str,
        model: str,
        client: genai.Client | None = None,
    ) -> None:
        self.client = client or genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=types.HttpOptions(api_version="v1"),
        )
        self.model = model

    # 問い合わせを分析する
    def analyze(self, title: str, raw_question: str) -> TicketAnalysis:
        response = self.client.models.generate_content(
            model=self.model,
            contents=f"タイトル: {title}\n問い合わせ: {raw_question}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0,
                response_mime_type="application/json",
                response_schema=TicketAnalysis,
            ),
        )
        if not isinstance(response.parsed, TicketAnalysis):
            raise ValueError("Gemini response could not be parsed")
        return response.parsed
