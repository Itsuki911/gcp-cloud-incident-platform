from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from incident_platform.config import get_settings


def test_initial_migration_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_path = tmp_path / "migration-test.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    project_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(project_root / "alembic.ini")
    engine = create_engine(database_url)

    try:
        command.upgrade(alembic_config, "head")
        table_names = set(inspect(engine).get_table_names())
        assert {"alembic_version", "attachments", "processed_events", "tickets"} <= table_names

        processed_event_columns = {
            column["name"] for column in inspect(engine).get_columns("processed_events")
        }
        assert {
            "event_id",
            "event_type",
            "ticket_id",
            "status",
            "attempt_count",
            "first_received_at",
            "completed_at",
            "last_error",
        } == processed_event_columns

        command.check(alembic_config)
        command.downgrade(alembic_config, "base")
        table_names = set(inspect(engine).get_table_names())
        assert "attachments" not in table_names
        assert "processed_events" not in table_names
        assert "tickets" not in table_names
    finally:
        engine.dispose()
        get_settings.cache_clear()
