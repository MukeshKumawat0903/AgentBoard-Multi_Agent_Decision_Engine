"""
Data paths must not depend on the directory the server is started from, and
the sqlite URL form must point every component (Alembic, aiosqlite,
checkpointer) at the same file.
"""

import sqlite3
from pathlib import Path

import pytest

from app.core.config import BACKEND_DIR, Settings, settings


def _settings(**env) -> Settings:
    return Settings(_env_file=None, GROQ_API_KEY="test", **env)  # type: ignore[call-arg]


def test_relative_paths_are_anchored_to_backend_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # start "from somewhere else"
    s = _settings(DATABASE_URL="agentboard.db", KNOWLEDGE_BASE_DIR="knowledge_base")

    assert Path(s.DATABASE_URL) == BACKEND_DIR / "agentboard.db"
    assert Path(s.KNOWLEDGE_BASE_DIR) == BACKEND_DIR / "knowledge_base"
    assert Path(s.CHECKPOINT_DATABASE_URL) == BACKEND_DIR / "agentboard_checkpoints.db"


@pytest.mark.parametrize("prefix", ["sqlite:///", "sqlite+aiosqlite:///"])
def test_sqlite_url_form_becomes_a_plain_path(prefix, tmp_path):
    target = tmp_path / "x.db"
    assert Path(_settings(DATABASE_URL=f"{prefix}{target}").DATABASE_URL) == target


def test_absolute_paths_and_memory_are_untouched(tmp_path):
    assert _settings(DATABASE_URL=str(tmp_path / "a.db")).DATABASE_URL == str(tmp_path / "a.db")
    assert _settings(CHECKPOINT_DATABASE_URL=":memory:").CHECKPOINT_DATABASE_URL == ":memory:"


def test_migrations_and_app_use_the_same_file_for_a_url(monkeypatch, tmp_path):
    from app.db.database import run_migrations

    target = tmp_path / "url.db"
    resolved = _settings(DATABASE_URL=f"sqlite:///{target}").DATABASE_URL
    monkeypatch.setattr(settings, "DATABASE_URL", resolved)
    run_migrations()

    with sqlite3.connect(target) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"debates", "decisions", "debate_events"} <= tables
    assert not any(p.name.startswith("sqlite:") for p in tmp_path.iterdir())
