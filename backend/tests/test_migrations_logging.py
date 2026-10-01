"""
Running the Alembic migrations at startup must not interfere with the
application's own logging configuration.
"""

import logging

import app.main  # noqa: F401  (imports every module, creating the module-level loggers)
from app.db.database import run_migrations

_APP_LOGGERS = [
    "agentboard",
    "agentboard.api",
    "agentboard.audit",
    "agentboard.db",
    "agentboard.nodes",
    "agentboard.services.llm_client",
]


def test_run_migrations_keeps_application_loggers_enabled():
    run_migrations()
    disabled = [name for name in _APP_LOGGERS if logging.getLogger(name).disabled]
    assert disabled == []


def test_run_migrations_does_not_reconfigure_root_logger():
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    level_before = root.level
    run_migrations()
    assert root.handlers == handlers_before
    assert root.level == level_before


def test_log_file_has_a_fixed_name_so_old_rotations_are_pruned(tmp_path):
    """Rotated files share one base name, so backupCount prunes them across
    restarts (a date in the base name started a new, never-pruned set each run)."""
    from logging.handlers import TimedRotatingFileHandler

    from app.core.logging_config import setup_logging

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    for day in range(1, 36):  # 35 rotated days left by earlier runs
        (log_dir / f"agentboard.log.2026-08-{day:02d}" if day <= 31 else log_dir / f"agentboard.log.2026-09-{day - 31:02d}").write_text("x")

    setup_logging("INFO", str(log_dir))
    handler = next(
        h for h in logging.getLogger("agentboard").handlers if isinstance(h, TimedRotatingFileHandler)
    )
    try:
        assert handler.baseFilename == str(log_dir / "agentboard.log")
        to_delete = handler.getFilesToDelete()
        assert len(to_delete) == 35 - handler.backupCount
        assert all(".2026-08-0" in name for name in to_delete)  # the oldest ones
    finally:
        handler.close()
        logging.getLogger("agentboard").removeHandler(handler)
