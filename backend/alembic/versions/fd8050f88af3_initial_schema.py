"""initial_schema

Revision ID: fd8050f88af3
Revises: 
Create Date: 2026-03-20 16:46:23.401215

Creates the three core tables (debates, decisions, debate_events)
plus their associated indexes.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fd8050f88af3'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "debates",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("user_query", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_round", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("max_rounds", sa.Integer(), nullable=True, server_default="4"),
        sa.Column("agreement_score", sa.REAL(), nullable=True, server_default="0.0"),
        sa.Column("termination_reason", sa.Text(), nullable=True),
        sa.Column("state_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("thread_id"),
    )
    op.create_index("idx_debates_created", "debates", ["created_at"], unique=False)

    op.create_table(
        "decisions",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("user_query", sa.Text(), nullable=False),
        sa.Column("decision_text", sa.Text(), nullable=False),
        sa.Column("decision_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("thread_id"),
    )
    op.create_index("idx_decisions_created", "decisions", ["created_at"], unique=False)

    op.create_table(
        "debate_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_debate_events_thread_event_id",
        "debate_events",
        ["thread_id", "event_id"],
        unique=False,
    )
    op.create_index(
        "idx_debate_events_created",
        "debate_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_debate_events_created", table_name="debate_events")
    op.drop_index("idx_debate_events_thread_event_id", table_name="debate_events")
    op.drop_table("debate_events")
    op.drop_index("idx_decisions_created", table_name="decisions")
    op.drop_table("decisions")
    op.drop_index("idx_debates_created", table_name="debates")
    op.drop_table("debates")
