"""phase3_phase4_tables

Revision ID: a1b2c3d4e5f6
Revises: fd8050f88af3
Create Date: 2026-03-20

Adds:
- agent_memory table (P3.3 Agent Memory)
- evaluation_json column on decisions table (P4.3 Decision Quality Evaluation)

"""
from typing import Sequence, Union

from alembic import op  # type: ignore[attr-defined]
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'fd8050f88af3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Agent Memory table (P3.3) ---
    op.create_table(
        "agent_memory",
        sa.Column("memory_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("debate_id", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("lesson_learned", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_agent_memory_agent_created",
        "agent_memory",
        ["agent_name", "created_at"],
        unique=False,
    )

    # --- evaluation_json column on decisions (P4.3) ---
    # SQLite does not support adding NOT NULL columns without a default.
    # We use nullable=True for the optional cache column.
    op.add_column(
        "decisions",
        sa.Column("evaluation_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # SQLite does not support DROP COLUMN; skip the column removal gracefully.
    op.drop_index("idx_agent_memory_agent_created", table_name="agent_memory")
    op.drop_table("agent_memory")
