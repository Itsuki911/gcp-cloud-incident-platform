[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install it from https://docs.astral.sh/uv/."
}

$env:UV_CACHE_DIR = Join-Path $ProjectRoot ".uv-cache"
uv sync

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Created .env from .env.example. Update GOOGLE_CLOUD_PROJECT before cloud use."
}

uv run python --version
uv run python -c "import alembic, fastapi, pydantic, sqlalchemy; print(f'Alembic {alembic.__version__}'); print(f'FastAPI {fastapi.__version__}'); print(f'Pydantic {pydantic.__version__}'); print(f'SQLAlchemy {sqlalchemy.__version__}')"
uv run alembic upgrade head
uv run pytest
