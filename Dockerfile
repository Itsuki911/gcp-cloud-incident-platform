# syntax=docker/dockerfile:1
# Pythonの軽量イメージを使用
FROM python:3.11.15-slim

# uvのバージョンを定義
ARG UV_VERSION=0.12.3

# Pythonと実行パスを設定
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# 作業ディレクトリを設定
WORKDIR /app

# Pythonパッケージ管理ツールを導入
RUN pip install --no-cache-dir "uv==${UV_VERSION}"

# 依存関係ファイルをコピー
COPY pyproject.toml uv.lock README.md ./
# DBマイグレーション設定をコピー
COPY alembic.ini ./
COPY migrations ./migrations
# アプリケーションコードをコピー
COPY src ./src
# 本番用の依存関係をインストール
RUN uv sync --frozen --no-dev

# APIが使用するポートを記録
EXPOSE 8080

# FastAPIアプリケーションを起動
CMD ["uvicorn", "incident_platform.main:app", "--host", "0.0.0.0", "--port", "8080"]
