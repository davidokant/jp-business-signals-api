from __future__ import annotations

import shutil
import sqlite3
from argparse import Namespace
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from .config import Settings
from .ingest import _sync_gbiz, build_parser
from .repository import Repository


def refresh_gbiz_database(settings: Settings, *, max_pages: int = 10) -> None:
    """Build a verified refresh copy, then atomically replace the live SQLite file."""
    database_path = Path(settings.database_path)
    working_path = database_path.with_name(f"{database_path.stem}.refresh{database_path.suffix}")
    backup_path = database_path.with_name(f"{database_path.stem}.backup{database_path.suffix}")
    working_path.unlink(missing_ok=True)
    if database_path.exists():
        shutil.copy2(database_path, working_path)

    try:
        working_settings = replace(settings, database_path=working_path)
        working_repository = Repository(working_path)
        working_repository.initialize()
        today = date.today()
        args = Namespace(
            command="gbiz",
            from_date=today - timedelta(days=8),
            to_date=today,
            max_pages=max_pages,
            reset=False,
            skip_procurement=False,
            terms_confirmed=True,
        )
        _sync_gbiz(args, working_settings, working_repository, build_parser())
        with sqlite3.connect(working_path) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            companies = connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
            sources = connection.execute(
                "SELECT COUNT(DISTINCT source_name) FROM companies"
            ).fetchone()[0]
        if integrity != "ok" or not companies or not sources:
            raise RuntimeError("Refreshed database failed integrity or coverage verification")
        if database_path.exists():
            shutil.copy2(database_path, backup_path)
        working_path.replace(database_path)
    finally:
        working_path.unlink(missing_ok=True)
