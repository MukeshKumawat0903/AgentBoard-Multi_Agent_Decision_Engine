"""
Guards for the test harness itself: every test must run against throw-away
storage so the suite can never pollute (or depend on) a developer's database.
"""

from pathlib import Path

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app


def test_persistence_paths_point_into_tmp_path(tmp_path):
    for configured in (
        settings.DATABASE_URL,
        settings.CHECKPOINT_DATABASE_URL,
        settings.KNOWLEDGE_BASE_DIR,
        settings.LOG_DIR,
    ):
        assert Path(configured).parent == tmp_path


@pytest.mark.anyio
async def test_isolated_database_is_fully_migrated():
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        tables = {row[0] for row in await cur.fetchall()}
    assert {"debates", "decisions", "debate_events", "agent_memory", "alembic_version"} <= tables


@pytest.mark.anyio
async def test_history_endpoint_works_on_a_fresh_database():
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/history")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
