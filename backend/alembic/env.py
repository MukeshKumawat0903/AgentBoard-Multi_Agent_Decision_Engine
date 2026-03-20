"""
Alembic migration environment.

Reads DATABASE_URL from app settings and converts aiosqlite:// URLs to
standard sqlite:// so the synchronous SQLAlchemy engine works correctly
for offline/online migration runs.
"""

import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# ---------------------------------------------------------------------------
# Make sure backend/app is importable when alembic is run from backend/
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402

# This is the Alembic Config object.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Build a synchronous sqlite:// URL from whatever DATABASE_URL is configured.
# aiosqlite uses "sqlite+aiosqlite://..." but Alembic needs plain "sqlite://..."
_db_url = settings.DATABASE_URL
if not _db_url.startswith("sqlite"):
    _db_url = f"sqlite:///{_db_url}"
elif _db_url.startswith("sqlite+aiosqlite"):
    _db_url = _db_url.replace("sqlite+aiosqlite", "sqlite", 1)
elif not _db_url.startswith("sqlite:///") and not _db_url.startswith("sqlite://"):
    _db_url = f"sqlite:///{_db_url}"

config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for SQLite column alterations
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (apply to live DB)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # required for SQLite column alterations
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
