from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from .schemas import FederalOpportunitySearchResponse


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SamBudgetExceeded(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("SAM.gov daily request budget exhausted")
        self.retry_after_seconds = retry_after_seconds


class SamQueryCoordinator:
    """Process-local cache and conservative daily guard for SAM.gov searches."""

    def __init__(
        self,
        *,
        client_factory: Callable[..., Any],
        api_key: str | None,
        base_url: str,
        timeout_seconds: float,
        daily_request_budget: int,
        cache_ttl_seconds: float,
        cache_max_entries: int,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client_factory = client_factory
        self._api_key = api_key
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._daily_request_budget = daily_request_budget
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache_max_entries = cache_max_entries
        self._monotonic = monotonic
        self._utc_now = utc_now
        self._cache: OrderedDict[
            tuple[tuple[str, object], ...],
            tuple[float, FederalOpportunitySearchResponse],
        ] = OrderedDict()
        self._budget_day = utc_now().date()
        self._budget_used = 0
        self._lock = threading.Lock()

    def search(self, **query: Any) -> FederalOpportunitySearchResponse:
        if not self._api_key:
            raise RuntimeError("SAM.gov opportunity source is not configured")
        cache_key = tuple(
            sorted((name, _freeze(value)) for name, value in query.items())
        )
        now = self._monotonic()
        current_utc = self._utc_now()
        with self._lock:
            self._reset_budget_if_needed(current_utc)
            cached = self._cache.get(cache_key)
            if cached and cached[0] > now:
                self._cache.move_to_end(cache_key)
                return cached[1].model_copy(deep=True)
            if cached:
                del self._cache[cache_key]
            if self._budget_used >= self._daily_request_budget:
                raise SamBudgetExceeded(_seconds_until_next_utc_day(current_utc))
            self._budget_used += 1

        with self._client_factory(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout_seconds=self._timeout_seconds,
        ) as client:
            response = client.search_opportunities(**query)

        with self._lock:
            self._cache[cache_key] = (
                now + self._cache_ttl_seconds,
                response.model_copy(deep=True),
            )
            self._cache.move_to_end(cache_key)
            while len(self._cache) > self._cache_max_entries:
                self._cache.popitem(last=False)
        return response

    def _reset_budget_if_needed(self, current_utc: datetime) -> None:
        day = current_utc.date()
        if day != self._budget_day:
            self._budget_day = day
            self._budget_used = 0


def _freeze(value: Any) -> object:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _seconds_until_next_utc_day(current_utc: datetime) -> int:
    next_day = datetime.combine(
        current_utc.date() + timedelta(days=1),
        datetime.min.time(),
        tzinfo=UTC,
    )
    return max(1, int((next_day - current_utc).total_seconds()))
