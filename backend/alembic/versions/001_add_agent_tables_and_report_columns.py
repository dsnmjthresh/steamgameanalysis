"""Add agent_runs, agent_checkpoints tables and missing ORM columns.

Creates the two agent-persistence tables used by ``AgentStateMachine`` in
``app/agent/runtime.py``, and adds the three reproducibility columns
(``model``, ``prompt_version``, ``tool_versions``) read by
``app/services/report_service.py``.  Also adds the ``user_id`` foreign key
that the ``Conversation`` model expects on ``conversations``.

All new columns are nullable — no data migration required.

Revision ID: 001
Revises: 000
Create Date: 2026-06-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "001"
down_revision: str | None = "000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. agent_runs ──────────────────────────────────────────────────
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id"),
            index=True,
            nullable=True,
        ),
        sa.Column("trace_id", sa.String(32), index=True, nullable=True),
        sa.Column("state", sa.String(32), nullable=False, server_default="INIT"),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("input_query", sa.Text(), nullable=True),
        sa.Column("output_answer", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_agent_runs_conv_status",
        "agent_runs",
        ["conversation_id", "status"],
    )

    # ── 2. agent_checkpoints ───────────────────────────────────────────
    op.create_table(
        "agent_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("agent_runs.id"),
            index=True,
            nullable=False,
        ),
        sa.Column("trace_id", sa.String(32), index=True, nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("output_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="success"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_agent_checkpoints_run_state",
        "agent_checkpoints",
        ["run_id", "state"],
    )

    # ── 3. conversations.user_id ──────────────────────────────────────
    # Use raw SQL DDL to avoid batch-mode temp-table issues on SQLite.
    op.execute("ALTER TABLE conversations ADD COLUMN user_id INTEGER REFERENCES users(id)")
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    # ── 4. analysis_reports reproducibility columns ────────────────────
    # (ix_analysis_reports_created_at already exists from baseline —
    #  the model declared index=True on created_at since 000.)
    op.execute("ALTER TABLE analysis_reports ADD COLUMN model VARCHAR(64)")
    op.execute("ALTER TABLE analysis_reports ADD COLUMN prompt_version VARCHAR(32)")
    op.execute("ALTER TABLE analysis_reports ADD COLUMN tool_versions VARCHAR(512)")


def downgrade() -> None:
    # ── 4. analysis_reports reproducibility columns ────────────────────
    # SQLite does not support DROP COLUMN directly; use batch mode only
    # for downgrade (which is rarely used in practice and acceptable to be
    # slower).
    with op.batch_alter_table("analysis_reports") as batch_op:
        batch_op.drop_column("tool_versions")
        batch_op.drop_column("prompt_version")
        batch_op.drop_column("model")

    # ── 3. conversations.user_id ──────────────────────────────────────
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_column("user_id")

    # ── 2. agent_checkpoints ───────────────────────────────────────────
    op.drop_index("ix_agent_checkpoints_run_state", table_name="agent_checkpoints")
    op.drop_table("agent_checkpoints")

    # ── 1. agent_runs ──────────────────────────────────────────────────
    op.drop_index("ix_agent_runs_conv_status", table_name="agent_runs")
    op.drop_table("agent_runs")
