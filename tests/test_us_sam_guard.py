from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from us_federal_signals.sam_guard import SamBudgetExceeded, SamQueryCoordinator
from us_federal_signals.schemas import (
    FederalOpportunity,
    FederalOpportunitySearchResponse,
)


class _FakeSamClient:
    calls: list[dict[str, Any]] = []

    def __enter__(self) -> _FakeSamClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def search_opportunities(self, **query: Any) -> FederalOpportunitySearchResponse:
        self.calls.append(query)
        return FederalOpportunitySearchResponse(
            items=[
                FederalOpportunity(
                    notice_id=f"notice-{query['q']}",
                    title=f"Opportunity for {query['q']}",
                    source_name="SAM.gov Contract Opportunities",
                    source_url="https://sam.gov/opp/example/view",
                    source_license="Official API terms apply",
                    collected_at=datetime.now(UTC),
                )
            ],
            count=1,
            limit=query.get("limit", 1),
            page=query.get("page", 0),
        )


def _factory(**_: Any) -> _FakeSamClient:
    return _FakeSamClient()


def _coordinator(
    *,
    budget: int = 1,
    monotonic=lambda: 0.0,
    utc_now=lambda: datetime(2026, 9, 1, 12, tzinfo=UTC),
) -> SamQueryCoordinator:
    return SamQueryCoordinator(
        client_factory=_factory,
        api_key="test-key",
        base_url="https://api.sam.gov/opportunities/v2/search",
        timeout_seconds=5,
        daily_request_budget=budget,
        cache_ttl_seconds=60,
        cache_max_entries=2,
        monotonic=monotonic,
        utc_now=utc_now,
    )


def test_sam_guard_reuses_cache_before_consuming_daily_budget() -> None:
    _FakeSamClient.calls.clear()
    coordinator = _coordinator()

    first = coordinator.search(q="cloud", limit=1, page=0)
    second = coordinator.search(q="cloud", limit=1, page=0)

    assert first == second
    assert len(_FakeSamClient.calls) == 1
    with pytest.raises(SamBudgetExceeded) as captured:
        coordinator.search(q="cybersecurity", limit=1, page=0)
    assert captured.value.retry_after_seconds == 43200


def test_sam_guard_resets_budget_on_the_next_utc_day() -> None:
    _FakeSamClient.calls.clear()
    moments = iter(
        [
            datetime(2026, 9, 1, 23, 59, tzinfo=UTC),
            datetime(2026, 9, 1, 23, 59, tzinfo=UTC),
            datetime(2026, 9, 2, 0, 1, tzinfo=UTC),
        ]
    )
    coordinator = _coordinator(utc_now=lambda: next(moments))

    coordinator.search(q="cloud", limit=1, page=0)
    result = coordinator.search(q="cybersecurity", limit=1, page=0)

    assert result.items[0].notice_id == "notice-cybersecurity"
    assert len(_FakeSamClient.calls) == 2


def test_sam_guard_expires_cache_entries() -> None:
    _FakeSamClient.calls.clear()
    ticks = iter([0.0, 61.0])
    coordinator = _coordinator(budget=2, monotonic=lambda: next(ticks))

    coordinator.search(q="cloud", limit=1, page=0)
    coordinator.search(q="cloud", limit=1, page=0)

    assert len(_FakeSamClient.calls) == 2
