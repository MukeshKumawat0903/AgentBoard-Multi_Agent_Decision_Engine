"""
History sorting, filtering and search run in SQL over the whole history, so
the first page of "highest agreement" or "human override" is correct no matter
how many debates exist. Search text is matched literally.
"""

from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.db.crud import get_history, save_decision
from app.main import app
from app.schemas.final_decision import FinalDecision

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _seed(rows: list[tuple[str, str, float, str]]) -> None:
    """rows: (thread_id, query, agreement_score, termination_reason), oldest first."""
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        for i, (thread_id, query, agreement, reason) in enumerate(rows):
            decision = FinalDecision(
                thread_id=thread_id,
                decision="Proceed",
                rationale_summary="why",
                confidence_score=0.8,
                agreement_score=agreement,
                total_rounds=2,
                termination_reason=reason,
                created_at=_BASE + timedelta(minutes=i),
            )
            await save_decision(db, decision, query)


def _many() -> list[tuple[str, str, float, str]]:
    """25 debates; the best agreement and the overrides are old, so they sit past page 1 by date."""
    rows = []
    for i in range(25):
        reason = "human_override" if i in (1, 7, 13) else "consensus_reached"
        agreement = 0.99 if i == 2 else 0.5 + i / 100
        rows.append((f"t{i:02d}", f"Question {i}", agreement, reason))
    return rows


@pytest.mark.anyio
async def test_highest_agreement_sorts_the_whole_history():
    await _seed(_many())
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        items, total = await get_history(db, page=1, limit=5, sort="highest_agreement")

    assert total == 25
    assert items[0]["thread_id"] == "t02"
    scores = [item["agreement_score"] for item in items]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.anyio
async def test_oldest_and_newest_sorts():
    await _seed(_many())
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        oldest, _ = await get_history(db, limit=3, sort="oldest")
        newest, _ = await get_history(db, limit=3)

    assert [i["thread_id"] for i in oldest] == ["t00", "t01", "t02"]
    assert [i["thread_id"] for i in newest] == ["t24", "t23", "t22"]


@pytest.mark.anyio
async def test_termination_filter_applies_before_paging():
    await _seed(_many())
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        page1, total = await get_history(db, page=1, limit=2, termination_reason="human_override")
        page2, _ = await get_history(db, page=2, limit=2, termination_reason="human_override")

    assert total == 3
    assert [i["thread_id"] for i in page1 + page2] == ["t13", "t07", "t01"]
    assert all(i["termination_reason"] == "human_override" for i in page1 + page2)


@pytest.mark.anyio
async def test_filter_search_and_sort_combine():
    await _seed(_many())
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        items, total = await get_history(
            db, q="Question 1", sort="oldest", termination_reason="consensus_reached"
        )

    # "Question 1" matches 1 and 10-19; 1 and 13 were overrides.
    assert total == 9
    assert items[0]["thread_id"] == "t10"


@pytest.mark.anyio
async def test_search_wildcards_match_literally():
    await _seed([
        ("pct", "Cut costs by 50% this year?", 0.6, "consensus_reached"),
        ("num", "Cut costs by 500 dollars?", 0.6, "consensus_reached"),
        ("und", "Rename user_id column?", 0.6, "consensus_reached"),
        ("sp", "Rename user id column?", 0.6, "consensus_reached"),
        ("bs", "Path C:\\temp cleanup?", 0.6, "consensus_reached"),
    ])
    async with aiosqlite.connect(settings.DATABASE_URL) as db:
        pct, _ = await get_history(db, q="50%")
        und, _ = await get_history(db, q="user_id")
        bs, _ = await get_history(db, q="C:\\temp")
        everything, total = await get_history(db, q="%")

    assert [i["thread_id"] for i in pct] == ["pct"]
    assert [i["thread_id"] for i in und] == ["und"]
    assert [i["thread_id"] for i in bs] == ["bs"]
    assert [i["thread_id"] for i in everything] == ["pct"]
    assert total == 1


@pytest.mark.anyio
async def test_history_route_passes_sort_and_filter():
    await _seed(_many())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:  # type: ignore[arg-type]
        resp = await client.get(
            "/history", params={"limit": 2, "sort": "highest_agreement", "termination_reason": "human_override"}
        )
        bad_sort = await client.get("/history", params={"sort": "agreement; DROP TABLE decisions"})
        bad_reason = await client.get("/history", params={"termination_reason": "anything"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert [i["thread_id"] for i in body["items"]] == ["t13", "t07"]
    assert bad_sort.status_code == 422
    assert bad_reason.status_code == 422
