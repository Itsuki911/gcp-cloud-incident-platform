# syntax=docker/dockerfile:1
FROM python:3.11.15-slim

ARG UV_VERSION=0.12.3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

EXPOSE 8080

CMD ["uvicorn", "incident_platform.main:app", "--host", "0.0.0.0", "--port", "8080"]

