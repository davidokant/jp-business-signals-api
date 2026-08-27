from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from .schemas import TenderOpportunity

TenderChangeAction = Literal["new", "updated", "deadline_changed", "expired"]

_ACTIONS = frozenset({"new", "updated", "deadline_changed", "expired"})
_DATETIME_FIELDS = (
    "collected_at",
    "published_at",
    "tender_submission_deadline",
    "opening_tenders_at",
    "delivery_due_at",
)
_TRACKED_FIELDS = (
    "title_ja",
    "buyer",
    "prefecture",
    "city",
    "category",
    "procedure_type",
    "qualification",
    "published_at",
    "tender_submission_deadline",
    "opening_tenders_at",
    "delivery_due_at",
    "source_name",
    "source_url",
    "source_license",
)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tender_snapshot_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tender_snapshots (
    tender_id TEXT PRIMARY KEY,
    metadata_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    deadline_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expired_at TEXT
);

CREATE TABLE IF NOT EXISTS tender_change_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_id TEXT NOT NULL REFERENCES tender_snapshots(tender_id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK (
        action IN ('new', 'updated', 'deadline_changed', 'expired')
    ),
    occurred_at TEXT NOT NULL,
    changed_fields_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tender_changes_occurred
    ON tender_change_events(occurred_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tender_changes_action_occurred
    ON tender_change_events(action, occurred_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tender_snapshots_deadline
    ON tender_snapshots(deadline_at)
    WHERE expired_at IS NULL;
"""


@dataclass(frozen=True, slots=True)
class TenderSnapshot:
    tender: TenderOpportunity
    first_seen_at: datetime
    last_seen_at: datetime
    expired_at: datetime | None

    @property
    def is_expired(self) -> bool:
        return self.expired_at is not None


@dataclass(frozen=True, slots=True)
class TenderChange:
    id: int
    tender_id: str
    action: TenderChangeAction
    occurred_at: datetime
    changed_fields: tuple[str, ...]
    tender: TenderOpportunity
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True, slots=True)
class TenderUpsertResult:
    snapshot: TenderSnapshot
    actions: tuple[TenderChangeAction, ...]
    changed_fields: tuple[str, ...]


class TenderHistoryStore:
    """Persist safe tender metadata and emit explicit, queryable change events.

    The store only knows about tenders passed to :meth:`upsert` or
    :meth:`upsert_many`. Absence from a later search result never deletes or
    expires a record because paginated and filtered source results are not a
    complete inventory.
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        """Apply the additive schema migration; safe to call repeatedly."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                """
                INSERT OR IGNORE INTO tender_snapshot_migrations(version, applied_at)
                VALUES (1, ?)
                """,
                (datetime.now(UTC).isoformat(),),
            )

    def upsert(
        self,
        tender: TenderOpportunity,
        *,
        observed_at: datetime | None = None,
    ) -> TenderUpsertResult:
        """Record one observation and return the transitions it produced."""
        return self.upsert_many([tender], observed_at=observed_at)[0]

    def upsert_many(
        self,
        tenders: Iterable[TenderOpportunity],
        *,
        observed_at: datetime | None = None,
    ) -> list[TenderUpsertResult]:
        """Atomically record observations without inferring anything from omissions."""
        items = list(tenders)
        if not items:
            return []

        explicit_observed_at = _normalize_datetime(observed_at) if observed_at else None
        results: list[TenderUpsertResult] = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for tender in items:
                timestamp = explicit_observed_at or _normalize_datetime(tender.collected_at)
                results.append(self._upsert_in_connection(connection, tender, timestamp))
        return results

    def get_snapshot(self, tender_id: str) -> TenderSnapshot | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tender_snapshots WHERE tender_id = ?", (tender_id,)
            ).fetchone()
        return _snapshot_from_row(row) if row else None

    def mark_expired(self, *, as_of: datetime) -> list[TenderChange]:
        """Mark records expired only when their stored deadline has passed."""
        timestamp = _normalize_datetime(as_of)
        timestamp_text = timestamp.isoformat()
        event_ids: list[int] = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT *
                FROM tender_snapshots
                WHERE expired_at IS NULL
                  AND deadline_at IS NOT NULL
                  AND deadline_at <= ?
                ORDER BY tender_id
                """,
                (timestamp_text,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE tender_snapshots SET expired_at = ? WHERE tender_id = ?",
                    (timestamp_text, row["tender_id"]),
                )
                event_ids.append(
                    self._insert_event(
                        connection,
                        tender_id=row["tender_id"],
                        action="expired",
                        occurred_at=timestamp,
                        changed_fields=("tender_submission_deadline",),
                        metadata_json=row["metadata_json"],
                        first_seen_at=row["first_seen_at"],
                        last_seen_at=row["last_seen_at"],
                    )
                )
        return self._changes_by_ids(event_ids)

    def list_changes(
        self,
        *,
        since: datetime | None = None,
        action: TenderChangeAction | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TenderChange]:
        if action is not None and action not in _ACTIONS:
            raise ValueError(f"Unsupported tender change action: {action}")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        clauses = ["1 = 1"]
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if since is not None:
            clauses.append("occurred_at >= :since")
            params["since"] = _normalize_datetime(since).isoformat()
        if action is not None:
            clauses.append("action = :action")
            params["action"] = action

        query = f"""
            SELECT *
            FROM tender_change_events
            WHERE {" AND ".join(clauses)}
            ORDER BY occurred_at DESC, id DESC
            LIMIT :limit OFFSET :offset
        """
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_change_from_row(row) for row in rows]

    def _upsert_in_connection(
        self,
        connection: sqlite3.Connection,
        tender: TenderOpportunity,
        observed_at: datetime,
    ) -> TenderUpsertResult:
        payload = _safe_payload(tender)
        metadata_json = _canonical_json(payload)
        content_hash = _content_hash(payload)
        deadline_at = payload["tender_submission_deadline"]
        timestamp_text = observed_at.isoformat()
        existing = connection.execute(
            "SELECT * FROM tender_snapshots WHERE tender_id = ?", (tender.tender_id,)
        ).fetchone()

        actions: list[TenderChangeAction] = []
        changed_fields: tuple[str, ...] = ()
        if existing is None:
            connection.execute(
                """
                INSERT INTO tender_snapshots (
                    tender_id, metadata_json, content_hash, deadline_at,
                    first_seen_at, last_seen_at, expired_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    tender.tender_id,
                    metadata_json,
                    content_hash,
                    deadline_at,
                    timestamp_text,
                    timestamp_text,
                ),
            )
            self._insert_event(
                connection,
                tender_id=tender.tender_id,
                action="new",
                occurred_at=observed_at,
                changed_fields=(),
                metadata_json=metadata_json,
                first_seen_at=timestamp_text,
                last_seen_at=timestamp_text,
            )
            actions.append("new")
            first_seen_at = observed_at
            expired_at = None
        else:
            last_seen_at = _parse_datetime(existing["last_seen_at"])
            if observed_at < last_seen_at:
                raise ValueError("observed_at cannot be earlier than the stored last_seen_at")

            old_payload = json.loads(existing["metadata_json"])
            changed_fields = tuple(
                field for field in _TRACKED_FIELDS if old_payload.get(field) != payload.get(field)
            )
            ordinary_changes = tuple(
                field for field in changed_fields if field != "tender_submission_deadline"
            )
            deadline_changed = "tender_submission_deadline" in changed_fields
            first_seen_at = _parse_datetime(existing["first_seen_at"])
            expired_at = _optional_datetime(existing["expired_at"])

            if deadline_changed and not _deadline_passed(deadline_at, observed_at):
                expired_at = None

            connection.execute(
                """
                UPDATE tender_snapshots
                SET metadata_json = ?, content_hash = ?, deadline_at = ?,
                    last_seen_at = ?, expired_at = ?
                WHERE tender_id = ?
                """,
                (
                    metadata_json,
                    content_hash,
                    deadline_at,
                    timestamp_text,
                    expired_at.isoformat() if expired_at else None,
                    tender.tender_id,
                ),
            )
            if ordinary_changes:
                self._insert_event(
                    connection,
                    tender_id=tender.tender_id,
                    action="updated",
                    occurred_at=observed_at,
                    changed_fields=ordinary_changes,
                    metadata_json=metadata_json,
                    first_seen_at=first_seen_at.isoformat(),
                    last_seen_at=timestamp_text,
                )
                actions.append("updated")
            if deadline_changed:
                self._insert_event(
                    connection,
                    tender_id=tender.tender_id,
                    action="deadline_changed",
                    occurred_at=observed_at,
                    changed_fields=("tender_submission_deadline",),
                    metadata_json=metadata_json,
                    first_seen_at=first_seen_at.isoformat(),
                    last_seen_at=timestamp_text,
                )
                actions.append("deadline_changed")

        if expired_at is None and _deadline_passed(deadline_at, observed_at):
            expired_at = observed_at
            connection.execute(
                "UPDATE tender_snapshots SET expired_at = ? WHERE tender_id = ?",
                (timestamp_text, tender.tender_id),
            )
            self._insert_event(
                connection,
                tender_id=tender.tender_id,
                action="expired",
                occurred_at=observed_at,
                changed_fields=("tender_submission_deadline",),
                metadata_json=metadata_json,
                first_seen_at=first_seen_at.isoformat(),
                last_seen_at=timestamp_text,
            )
            actions.append("expired")

        snapshot = TenderSnapshot(
            tender=TenderOpportunity.model_validate(payload),
            first_seen_at=first_seen_at,
            last_seen_at=observed_at,
            expired_at=expired_at,
        )
        return TenderUpsertResult(
            snapshot=snapshot,
            actions=tuple(actions),
            changed_fields=changed_fields,
        )

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        tender_id: str,
        action: TenderChangeAction,
        occurred_at: datetime,
        changed_fields: tuple[str, ...],
        metadata_json: str,
        first_seen_at: str,
        last_seen_at: str,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO tender_change_events (
                tender_id, action, occurred_at, changed_fields_json,
                metadata_json, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tender_id,
                action,
                occurred_at.isoformat(),
                _canonical_json(list(changed_fields)),
                metadata_json,
                first_seen_at,
                last_seen_at,
            ),
        )
        return int(cursor.lastrowid)

    def _changes_by_ids(self, event_ids: list[int]) -> list[TenderChange]:
        if not event_ids:
            return []
        placeholders = ",".join("?" for _ in event_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM tender_change_events
                WHERE id IN ({placeholders})
                ORDER BY occurred_at DESC, id DESC
                """,
                event_ids,
            ).fetchall()
        return [_change_from_row(row) for row in rows]


def _safe_payload(tender: TenderOpportunity) -> dict[str, object]:
    payload = tender.model_dump(mode="json")
    payload["source_url"] = str(tender.source_url)
    payload["qualification"] = sorted(
        {value.strip() for value in tender.qualification if value.strip()}
    )
    for field in _DATETIME_FIELDS:
        value = getattr(tender, field)
        payload[field] = _normalize_datetime(value).isoformat() if value is not None else None
    return payload


def _content_hash(payload: dict[str, object]) -> str:
    tracked = {field: payload[field] for field in _TRACKED_FIELDS}
    return hashlib.sha256(_canonical_json(tracked).encode()).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _deadline_passed(deadline_at: object, observed_at: datetime) -> bool:
    if not isinstance(deadline_at, str):
        return False
    return _parse_datetime(deadline_at) <= observed_at


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Tender history timestamps must include a timezone")
    return value.astimezone(UTC)


def _parse_datetime(value: str) -> datetime:
    return _normalize_datetime(datetime.fromisoformat(value))


def _optional_datetime(value: str | None) -> datetime | None:
    return _parse_datetime(value) if value else None


def _snapshot_from_row(row: sqlite3.Row) -> TenderSnapshot:
    return TenderSnapshot(
        tender=TenderOpportunity.model_validate(json.loads(row["metadata_json"])),
        first_seen_at=_parse_datetime(row["first_seen_at"]),
        last_seen_at=_parse_datetime(row["last_seen_at"]),
        expired_at=_optional_datetime(row["expired_at"]),
    )


def _change_from_row(row: sqlite3.Row) -> TenderChange:
    return TenderChange(
        id=int(row["id"]),
        tender_id=row["tender_id"],
        action=cast(TenderChangeAction, row["action"]),
        occurred_at=_parse_datetime(row["occurred_at"]),
        changed_fields=tuple(json.loads(row["changed_fields_json"])),
        tender=TenderOpportunity.model_validate(json.loads(row["metadata_json"])),
        first_seen_at=_parse_datetime(row["first_seen_at"]),
        last_seen_at=_parse_datetime(row["last_seen_at"]),
    )
