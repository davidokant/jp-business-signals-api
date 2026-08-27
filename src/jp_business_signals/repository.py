from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from .schemas import (
    Company,
    DemoSignal,
    DemoStats,
    ProcurementSignal,
    PublicDataStatus,
    Signal,
    SourceSummary,
)
from .scoring import calculate_activity_score

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    corporate_number TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_kana TEXT,
    prefecture TEXT,
    city TEXT,
    industry TEXT,
    homepage_url TEXT,
    activity_score INTEGER NOT NULL CHECK (activity_score BETWEEN 0 AND 100),
    procurement_count INTEGER NOT NULL CHECK (procurement_count >= 0),
    subsidy_count INTEGER NOT NULL CHECK (subsidy_count >= 0),
    patent_count INTEGER NOT NULL CHECK (patent_count >= 0),
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_license TEXT NOT NULL,
    source_updated_at TEXT,
    collected_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corporate_number TEXT NOT NULL REFERENCES companies(corporate_number) ON DELETE CASCADE,
    signal_type TEXT NOT NULL,
    title TEXT NOT NULL,
    occurred_on TEXT NOT NULL,
    score_delta INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_license TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    UNIQUE(corporate_number, signal_type, title, occurred_on, source_url)
);

CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name);
CREATE INDEX IF NOT EXISTS idx_companies_prefecture ON companies(prefecture);
CREATE INDEX IF NOT EXISTS idx_companies_industry ON companies(industry);
CREATE INDEX IF NOT EXISTS idx_companies_activity ON companies(activity_score DESC);
CREATE INDEX IF NOT EXISTS idx_signals_occurred ON signals(occurred_on DESC);
CREATE INDEX IF NOT EXISTS idx_signals_type ON signals(signal_type);
"""


class Repository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def count_companies(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM companies").fetchone()
        return int(row["count"])

    def reset(self) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM signals")
            connection.execute("DELETE FROM companies")

    def upsert_companies(self, companies: Iterable[Company]) -> int:
        payload = [self._company_values(company) for company in companies]
        if not payload:
            return 0
        sql = """
        INSERT INTO companies (
            corporate_number, name, name_kana, prefecture, city, industry, homepage_url,
            activity_score, procurement_count, subsidy_count, patent_count, source_name,
            source_url, source_license, source_updated_at, collected_at
        ) VALUES (
            :corporate_number, :name, :name_kana, :prefecture, :city, :industry, :homepage_url,
            :activity_score, :procurement_count, :subsidy_count, :patent_count, :source_name,
            :source_url, :source_license, :source_updated_at, :collected_at
        )
        ON CONFLICT(corporate_number) DO UPDATE SET
            name=excluded.name,
            name_kana=excluded.name_kana,
            prefecture=excluded.prefecture,
            city=excluded.city,
            industry=excluded.industry,
            homepage_url=excluded.homepage_url,
            activity_score=excluded.activity_score,
            procurement_count=excluded.procurement_count,
            subsidy_count=excluded.subsidy_count,
            patent_count=excluded.patent_count,
            source_name=excluded.source_name,
            source_url=excluded.source_url,
            source_license=excluded.source_license,
            source_updated_at=excluded.source_updated_at,
            collected_at=excluded.collected_at
        """
        with self.connect() as connection:
            connection.executemany(sql, payload)
        return len(payload)

    def insert_signals(self, signals: Iterable[Signal]) -> int:
        payload = [self._signal_values(signal) for signal in signals]
        if not payload:
            return 0
        before: int
        after: int
        with self.connect() as connection:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT OR IGNORE INTO signals (
                    corporate_number, signal_type, title, occurred_on, score_delta,
                    source_name, source_url, source_license, collected_at
                ) VALUES (
                    :corporate_number, :signal_type, :title, :occurred_on, :score_delta,
                    :source_name, :source_url, :source_license, :collected_at
                )
                """,
                payload,
            )
            after = connection.total_changes
        return after - before

    def insert_companies_if_missing(self, companies: Iterable[Company]) -> int:
        payload = [self._company_values(company) for company in companies]
        if not payload:
            return 0
        sql = """
        INSERT INTO companies (
            corporate_number, name, name_kana, prefecture, city, industry, homepage_url,
            activity_score, procurement_count, subsidy_count, patent_count, source_name,
            source_url, source_license, source_updated_at, collected_at
        ) VALUES (
            :corporate_number, :name, :name_kana, :prefecture, :city, :industry, :homepage_url,
            :activity_score, :procurement_count, :subsidy_count, :patent_count, :source_name,
            :source_url, :source_license, :source_updated_at, :collected_at
        )
        ON CONFLICT(corporate_number) DO NOTHING
        """
        with self.connect() as connection:
            before = connection.total_changes
            connection.executemany(sql, payload)
            inserted = connection.total_changes - before
        return inserted

    def refresh_activity_metrics(self, corporate_numbers: Iterable[str]) -> int:
        numbers = sorted(set(corporate_numbers))
        if not numbers:
            return 0
        placeholders = ",".join("?" for _ in numbers)
        query = f"""
        SELECT corporate_number, signal_type, COUNT(*) AS count
        FROM signals
        WHERE corporate_number IN ({placeholders})
          AND signal_type IN ('procurement', 'subsidy', 'patent', 'certification')
        GROUP BY corporate_number, signal_type
        """
        counts: dict[str, dict[str, int]] = {number: {} for number in numbers}
        with self.connect() as connection:
            for row in connection.execute(query, numbers):
                counts[row["corporate_number"]][row["signal_type"]] = int(row["count"])

            updates = []
            for corporate_number, signal_counts in counts.items():
                procurement_count = signal_counts.get("procurement", 0)
                subsidy_count = signal_counts.get("subsidy", 0)
                patent_count = signal_counts.get("patent", 0)
                certification_count = signal_counts.get("certification", 0)
                updates.append(
                    (
                        calculate_activity_score(
                            procurement_count=procurement_count,
                            subsidy_count=subsidy_count,
                            patent_count=patent_count,
                            certification_count=certification_count,
                        ),
                        procurement_count,
                        subsidy_count,
                        patent_count,
                        corporate_number,
                    )
                )
            connection.executemany(
                """
                UPDATE companies
                SET activity_score = ?,
                    procurement_count = ?,
                    subsidy_count = ?,
                    patent_count = ?
                WHERE corporate_number = ?
                """,
                updates,
            )
        return len(updates)

    def search_companies(
        self,
        *,
        q: str | None,
        prefecture: str | None,
        industry: str | None,
        min_activity_score: int,
        limit: int,
        offset: int,
    ) -> list[Company]:
        clauses = ["activity_score >= :min_activity_score"]
        params: dict[str, Any] = {
            "min_activity_score": min_activity_score,
            "limit": limit,
            "offset": offset,
        }
        if q:
            clauses.append("(name LIKE :q OR COALESCE(name_kana, '') LIKE :q)")
            params["q"] = f"%{q}%"
        if prefecture:
            clauses.append("LOWER(COALESCE(prefecture, '')) = LOWER(:prefecture)")
            params["prefecture"] = prefecture
        if industry:
            clauses.append("LOWER(COALESCE(industry, '')) LIKE LOWER(:industry)")
            params["industry"] = f"%{industry}%"

        query = f"""
            SELECT * FROM companies
            WHERE {" AND ".join(clauses)}
            ORDER BY activity_score DESC, corporate_number ASC
            LIMIT :limit OFFSET :offset
        """
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [Company.model_validate(dict(row)) for row in rows]

    def get_company(self, corporate_number: str) -> Company | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM companies WHERE corporate_number = ?", (corporate_number,)
            ).fetchone()
        return Company.model_validate(dict(row)) if row else None

    def list_signals(
        self,
        *,
        since: date | None,
        signal_type: str | None,
        corporate_number: str | None,
        limit: int,
        offset: int,
    ) -> list[Signal]:
        clauses = ["1 = 1"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if since:
            clauses.append("occurred_on >= :since")
            params["since"] = since.isoformat()
        if signal_type:
            clauses.append("signal_type = :signal_type")
            params["signal_type"] = signal_type
        if corporate_number:
            clauses.append("corporate_number = :corporate_number")
            params["corporate_number"] = corporate_number

        query = f"""
            SELECT * FROM signals
            WHERE {" AND ".join(clauses)}
            ORDER BY occurred_on DESC, id DESC
            LIMIT :limit OFFSET :offset
        """
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [Signal.model_validate(dict(row)) for row in rows]

    def search_procurement_signals(
        self,
        *,
        since: date | None,
        q: str | None,
        prefecture: str | None,
        limit: int,
        offset: int,
    ) -> list[ProcurementSignal]:
        """Return procurement events with company context for monitoring workflows."""
        clauses = ["s.signal_type = 'procurement'"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if since:
            clauses.append("s.occurred_on >= :since")
            params["since"] = since.isoformat()
        if q:
            clauses.append("(c.name LIKE :q OR s.title LIKE :q)")
            params["q"] = f"%{q}%"
        if prefecture:
            clauses.append("LOWER(COALESCE(c.prefecture, '')) = LOWER(:prefecture)")
            params["prefecture"] = prefecture

        query = f"""
            SELECT
                s.*,
                c.name AS company_name,
                c.prefecture,
                c.industry,
                c.activity_score
            FROM signals AS s
            JOIN companies AS c ON c.corporate_number = s.corporate_number
            WHERE {" AND ".join(clauses)}
            ORDER BY s.occurred_on DESC, s.id DESC
            LIMIT :limit OFFSET :offset
        """
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [ProcurementSignal.model_validate(dict(row)) for row in rows]

    def list_sources(self) -> list[SourceSummary]:
        query = """
        SELECT
            source_name,
            source_license,
            COUNT(*) AS record_count,
            MAX(collected_at) AS latest_collection
        FROM (
            SELECT source_name, source_license, collected_at FROM companies
            UNION ALL
            SELECT source_name, source_license, collected_at FROM signals
        )
        GROUP BY source_name, source_license
        ORDER BY source_name
        """
        with self.connect() as connection:
            rows = connection.execute(query).fetchall()
        return [SourceSummary.model_validate(dict(row)) for row in rows]

    def demo_stats(self) -> DemoStats:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM companies) AS companies,
                    (
                        SELECT COUNT(*) FROM signals
                        WHERE signal_type = 'procurement'
                    ) AS procurement_signals,
                    (
                        SELECT COUNT(*) FROM companies
                        WHERE procurement_count > 0
                    ) AS active_companies,
                    (
                        SELECT COUNT(DISTINCT source_name)
                        FROM companies
                    ) AS official_sources
                """
            ).fetchone()
        return DemoStats.model_validate(dict(row))

    def public_data_status(self) -> PublicDataStatus:
        """Return aggregate coverage information without exposing customer data."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM companies) AS companies,
                    (SELECT COUNT(*) FROM signals) AS signals,
                    (SELECT COUNT(DISTINCT source_name) FROM companies) AS official_sources,
                    (
                        SELECT MAX(collected_at)
                        FROM (
                            SELECT collected_at FROM companies
                            UNION ALL
                            SELECT collected_at FROM signals
                        )
                    ) AS latest_collection
                """
            ).fetchone()
        return PublicDataStatus.model_validate(dict(row))

    def search_demo_procurement(
        self,
        *,
        q: str | None,
        limit: int,
    ) -> list[DemoSignal]:
        params: dict[str, Any] = {"limit": limit}
        clauses = ["s.signal_type = 'procurement'"]
        if q:
            clauses.append("(c.name LIKE :q OR s.title LIKE :q)")
            params["q"] = f"%{q}%"
        query = f"""
            SELECT
                s.corporate_number,
                c.name AS company_name,
                c.prefecture,
                s.title,
                s.occurred_on,
                s.score_delta,
                c.activity_score,
                s.source_url
            FROM signals AS s
            JOIN companies AS c
              ON c.corporate_number = s.corporate_number
            WHERE {" AND ".join(clauses)}
            ORDER BY s.occurred_on DESC, s.id DESC
            LIMIT :limit
        """
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [DemoSignal.model_validate(dict(row)) for row in rows]

    @staticmethod
    def _company_values(company: Company) -> dict[str, Any]:
        data = company.model_dump(mode="json")
        for field in ("homepage_url", "source_url"):
            if data.get(field) is not None:
                data[field] = str(data[field])
        return data

    @staticmethod
    def _signal_values(signal: Signal) -> dict[str, Any]:
        data = signal.model_dump(mode="json", exclude={"id"})
        data["source_url"] = str(data["source_url"])
        return data
