"""Baseline migration — creates all tables from SQLModel metadata.

This is the starting point for fresh databases.  All subsequent incremental
migrations (001, 002, …) depend on this baseline.

Revision ID: 000
Revises: None (first revision)
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlmodel import SQLModel

# Import all models so SQLModel.metadata is fully populated
import app.db.models  # noqa: F401

# revision identifiers
revision: str = "000"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables from SQLModel metadata using batch mode for SQLite."""
    # Use SQLModel's create_all via the batch-compatible Alembic connection.
    # render_as_batch is configured in env.py so ALTER is safe for SQLite.
    # For the baseline we need create_table — Alembic's op doesn't have a
    # batch_create_all, so we use the raw connection with SQLModel metadata.
    bind = op.get_bind()

    # Drop any existing tables first (safety: only on fresh DBs or explicitly)
    # We don't drop here — assume running on an empty database.

    SQLModel.metadata.create_all(bind)


def downgrade() -> None:
    """Drop all tables."""
    SQLModel.metadata.drop_all(op.get_bind())
