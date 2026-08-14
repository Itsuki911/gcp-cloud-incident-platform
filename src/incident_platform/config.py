from functools import lru_cache
# 関数の戻り値をキャッシュ（記憶）する

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "Cloud-Native AI Incident & Support Triage System"
    #アプリケーション名
    app_env: str = "development"
    #実行環境名
    log_level: str = "INFO"
    #ログ出力レベル
    database_url: str = "postgresql+psycopg://incident:incident@localhost:5432/incidents"
    #DBへの接続URL
    model_config = SettingsConfigDict(
        #Pydanticの設定クラスの設定を定義するための辞書
        env_file=".env",
        env_file_encoding="utf-8", # utf-8:文字コード
        extra="ignore", # extra: 設定に含まれない環境変数を無視する
    )


@lru_cache # この関数の実行結果をメモリにキャッシュする
def get_settings() -> Settings:
    return Settings()
#get_settings関数：設定オブジェクト（Settings のインスタンス）を生成して返す