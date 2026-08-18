from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 関数の戻り値をキャッシュ（記憶）する


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "Cloud-Native AI Incident & Support Triage System"
    # アプリケーション名
    app_env: str = "development"
    # 実行環境名
    log_level: str = "INFO"
    # ログ出力レベル
    database_url: str = "postgresql+psycopg://incident:incident@localhost:5432/incidents"
    # DBへの接続URL
    google_cloud_project: str = "gcp-cloud-incident-platform"
    # Vertex AIのプロジェクト
    google_cloud_location: str = "global"
    # Geminiの呼び出し場所
    gemini_model: str = "gemini-2.5-flash-lite"
    # 使用するGeminiモデル
    use_local_analyzer: bool = False
    # ローカル分析を切り替える
    pubsub_topic: str = "incident-tickets"
    # Publish先のTopic名
    attachment_bucket: str = "gcp-cloud-incident-platform-ticket-attachments-888088780947"
    # 添付ファイルの保存先
    model_config = SettingsConfigDict(
        # Pydanticの設定クラスの設定を定義するための辞書
        env_file=".env",
        env_file_encoding="utf-8",  # utf-8:文字コード
        extra="ignore",  # extra: 設定に含まれない環境変数を無視する
    )


@lru_cache  # この関数の実行結果をメモリにキャッシュする
def get_settings() -> Settings:
    return Settings()


# get_settings関数：設定オブジェクト（Settings のインスタンス）を生成して返す
