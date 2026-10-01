"""agent_memory_nocase_index

Revision ID: c3e7a9f1b2d4
Revises: a1b2c3d4e5f6
Create Date: 2026-10-01

Agent memory is looked up with ``agent_name = ? COLLATE NOCASE``, which the
original ``(agent_name, created_at)`` index cannot serve, so every lookup
scanned the table and sorted it. Index the case-insensitive name instead.

"""
from typing import Sequence, Union

from alembic import op  # type: ignore[attr-defined]


# revision identifiers, used by Alembic.
revision: str = 'c3e7a9f1b2d4'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_memory_agent_nocase_created "
        "ON agent_memory (agent_name COLLATE NOCASE, created_at)"
    )
    op.execute("DROP INDEX IF EXISTS idx_agent_memory_agent_created")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_memory_agent_created "
        "ON agent_memory (agent_name, created_at)"
    )
    op.execute("DROP INDEX IF EXISTS idx_agent_memory_agent_nocase_created")
