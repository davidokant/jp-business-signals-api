from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from jp_business_signals.schemas import TenderOpportunity
from jp_business_signals.tender_history import TenderHistoryStore


def _tender(
    *,
    tender_id: str = "kkj-001",
    title: str = "クラウド基盤調達",
    collected_at: datetime,
    deadline: datetime | None,
) -> TenderOpportunity:
    return TenderOpportunity(
        tender_id=tender_id,
        title_ja=title,
        buyer="デジタル庁",
        prefecture="Tokyo",
        city="Chiyoda",
        category="services",
        procedure_type="open tender",
        qualification=["A", "B"],
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        tender_submission_deadline=deadline,
        opening_tenders_at=None,
        delivery_due_at=None,
        source_name="Japan Public Procurement Information Portal (KKJ)",
        source_url=f"https://www.kkj.go.jp/d/?A={tender_id}",
        source_license="KKJ terms of use",
        collected_at=collected_at,
    )


def test_initialize_is_idempotent_and_unchanged_observation_updates_last_seen(tmp_path) -> None:
    store = TenderHistoryStore(tmp_path / "history.db")
    store.initialize()
    store.initialize()
    first_seen = datetime(2026, 1, 2, 9, tzinfo=UTC)
    second_seen = datetime(2026, 1, 3, 9, tzinfo=UTC)
    deadline = datetime(2026, 2, 1, tzinfo=UTC)

    first = store.upsert(
        _tender(collected_at=first_seen, deadline=deadline), observed_at=first_seen
    )
    second = store.upsert(
        _tender(collected_at=second_seen, deadline=deadline), observed_at=second_seen
    )

    assert first.actions == ("new",)
    assert second.actions == ()
    assert second.snapshot.first_seen_at == first_seen
    assert second.snapshot.last_seen_at == second_seen
    assert [change.action for change in store.list_changes()] == ["new"]
    with sqlite3.connect(tmp_path / "history.db") as connection:
        migration_count = connection.execute(
            "SELECT COUNT(*) FROM tender_snapshot_migrations WHERE version = 1"
        ).fetchone()[0]
    assert migration_count == 1


def test_upsert_detects_metadata_and_deadline_changes_independently(tmp_path) -> None:
    store = TenderHistoryStore(tmp_path / "history.db")
    store.initialize()
    first_seen = datetime(2026, 1, 2, tzinfo=UTC)
    changed_at = datetime(2026, 1, 4, tzinfo=UTC)
    original_deadline = datetime(2026, 2, 1, tzinfo=UTC)
    extended_deadline = datetime(2026, 2, 8, tzinfo=UTC)
    store.upsert(
        _tender(collected_at=first_seen, deadline=original_deadline),
        observed_at=first_seen,
    )

    result = store.upsert(
        _tender(
            title="クラウド基盤調達（更新）",
            collected_at=changed_at,
            deadline=extended_deadline,
        ),
        observed_at=changed_at,
    )

    assert result.actions == ("updated", "deadline_changed")
    assert result.changed_fields == ("title_ja", "tender_submission_deadline")
    assert result.snapshot.tender.tender_submission_deadline == extended_deadline
    assert [change.changed_fields for change in store.list_changes(action="updated")] == [
        ("title_ja",)
    ]
    deadline_changes = store.list_changes(action="deadline_changed", since=changed_at)
    assert len(deadline_changes) == 1
    assert deadline_changes[0].occurred_at == changed_at


def test_missing_from_later_batch_is_preserved_and_expiry_uses_deadline(tmp_path) -> None:
    store = TenderHistoryStore(tmp_path / "history.db")
    store.initialize()
    first_seen = datetime(2026, 1, 2, tzinfo=UTC)
    later_scan = datetime(2026, 1, 3, tzinfo=UTC)
    deadline = datetime(2026, 2, 1, tzinfo=UTC)
    store.upsert_many(
        [_tender(collected_at=first_seen, deadline=deadline)], observed_at=first_seen
    )

    store.upsert_many(
        [
            _tender(
                tender_id="kkj-002",
                collected_at=later_scan,
                deadline=datetime(2026, 3, 1, tzinfo=UTC),
            )
        ],
        observed_at=later_scan,
    )

    preserved = store.get_snapshot("kkj-001")
    assert preserved is not None
    assert preserved.last_seen_at == first_seen
    assert not preserved.is_expired
    assert store.mark_expired(as_of=datetime(2026, 1, 31, tzinfo=UTC)) == []

    expired = store.mark_expired(as_of=datetime(2026, 2, 2, tzinfo=UTC))

    assert [change.tender_id for change in expired] == ["kkj-001"]
    assert expired[0].action == "expired"
    assert store.get_snapshot("kkj-001").is_expired  # type: ignore[union-attr]
    assert store.mark_expired(as_of=datetime(2026, 2, 3, tzinfo=UTC)) == []


def test_change_query_validates_filters_and_requires_timezone(tmp_path) -> None:
    store = TenderHistoryStore(tmp_path / "history.db")
    store.initialize()

    with pytest.raises(ValueError, match="timezone"):
        store.list_changes(since=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="Unsupported"):
        store.list_changes(action="deleted")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="limit"):
        store.list_changes(limit=0)
    with pytest.raises(ValueError, match="offset"):
        store.list_changes(offset=-1)
