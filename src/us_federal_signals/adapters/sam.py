from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Final

import httpx
from pydantic import ValidationError

from ..schemas import FederalOpportunity, FederalOpportunitySearchResponse

SAM_SOURCE_NAME: Final = "SAM.gov Contract Opportunities"
SAM_SOURCE_LICENSE: Final = (
    "SAM.gov Get Opportunities Public API; official API terms and usage limits apply"
)


class SamError(RuntimeError):
    """Raised when SAM.gov is unavailable or returns an invalid response."""


class SamRateLimitError(SamError):
    def __init__(self, retry_after_seconds: int = 60) -> None:
        super().__init__("SAM.gov request quota exhausted")
        self.retry_after_seconds = retry_after_seconds


class SamOpportunitiesClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.sam.gov/opportunities/v2/search",
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("A SAM.gov public API key is required")
        self._api_key = api_key
        self._search_url = base_url.rstrip("/")
        self._client = httpx.Client(
            headers={
                "Accept": "application/json",
                "User-Agent": "us-federal-signals-feasibility/0.1",
            },
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    def __enter__(self) -> SamOpportunitiesClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def search_opportunities(
        self,
        *,
        posted_from: date,
        posted_to: date,
        q: str | None = None,
        notice_types: list[str] | None = None,
        organization_name: str | None = None,
        state: str | None = None,
        naics_code: str | None = None,
        classification_code: str | None = None,
        set_aside_code: str | None = None,
        limit: int = 25,
        page: int = 0,
    ) -> FederalOpportunitySearchResponse:
        _validate_search(posted_from=posted_from, posted_to=posted_to, limit=limit, page=page)
        params: list[tuple[str, str]] = [
            ("api_key", self._api_key),
            ("postedFrom", posted_from.strftime("%m/%d/%Y")),
            ("postedTo", posted_to.strftime("%m/%d/%Y")),
            ("limit", str(limit)),
            ("offset", str(page)),
        ]
        if q:
            params.append(("title", q))
        for notice_type in notice_types or []:
            params.append(("ptype", notice_type))
        optional_params = {
            "organizationName": organization_name,
            "state": state,
            "ncode": naics_code,
            "ccode": classification_code,
            "typeOfSetAside": set_aside_code,
        }
        params.extend((key, value) for key, value in optional_params.items() if value)

        try:
            response = self._client.get(self._search_url, params=params)
            if response.status_code == 429:
                raise SamRateLimitError(_retry_after_seconds(response))
            response.raise_for_status()
            payload = response.json()
        except SamRateLimitError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise SamError("SAM.gov opportunities request failed") from exc
        return _parse_response(payload, limit=limit, page=page)


def _validate_search(*, posted_from: date, posted_to: date, limit: int, page: int) -> None:
    if posted_from > posted_to:
        raise ValueError("posted_from must be on or before posted_to")
    if (posted_to - posted_from).days > 366:
        raise ValueError("SAM.gov date ranges cannot exceed one year")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1,000")
    if page < 0:
        raise ValueError("page must be non-negative")


def _parse_response(
    payload: Any, *, limit: int, page: int
) -> FederalOpportunitySearchResponse:
    if not isinstance(payload, dict) or not isinstance(payload.get("opportunitiesData"), list):
        raise SamError("SAM.gov returned an invalid opportunities payload")
    collected_at = datetime.now(UTC)
    items: list[FederalOpportunity] = []
    for raw in payload["opportunitiesData"]:
        if not isinstance(raw, dict):
            continue
        try:
            items.append(_to_opportunity(raw, collected_at=collected_at))
        except (SamError, ValidationError):
            continue
    return FederalOpportunitySearchResponse(
        items=items,
        count=_nonnegative_int(payload.get("totalRecords")),
        limit=limit,
        page=page,
    )


def _to_opportunity(raw: dict[str, Any], *, collected_at: datetime) -> FederalOpportunity:
    notice_id = _string(raw.get("noticeId"))
    title = _string(raw.get("title"))
    if not notice_id or not title:
        raise SamError("SAM.gov opportunity is missing noticeId or title")
    performance = raw.get("placeOfPerformance")
    performance = performance if isinstance(performance, dict) else {}
    source_url = _valid_source_url(raw.get("uiLink")) or (
        f"https://sam.gov/opp/{notice_id}/view"
    )
    return FederalOpportunity(
        notice_id=notice_id,
        title=title,
        solicitation_number=_string(raw.get("solicitationNumber")) or None,
        organization_name=_organization_name(raw),
        notice_type=_string(raw.get("type")) or None,
        base_type=_string(raw.get("baseType")) or None,
        posted_date=_date_or_none(raw.get("postedDate")),
        response_deadline=_datetime_or_none(raw.get("responseDeadLine")),
        naics_code=_digits_or_none(raw.get("naicsCode"), maximum=6),
        classification_code=_string(raw.get("classificationCode")) or None,
        set_aside_code=_string(raw.get("typeOfSetAside")) or None,
        set_aside_description=_string(raw.get("typeOfSetAsideDescription")) or None,
        place_of_performance_state=_nested_name(performance.get("state")),
        place_of_performance_city=_nested_name(performance.get("city")),
        active=_bool_or_none(raw.get("active")),
        source_name=SAM_SOURCE_NAME,
        source_url=source_url,
        source_license=SAM_SOURCE_LICENSE,
        collected_at=collected_at,
    )


def _organization_name(raw: dict[str, Any]) -> str | None:
    path = _string(raw.get("fullParentPathName"))
    if path:
        return path
    levels = [
        _string(raw.get("department")),
        _string(raw.get("subTier")),
        _string(raw.get("office")),
    ]
    return " / ".join(value for value in levels if value) or None


def _nested_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return _string(value.get("code") or value.get("name")) or None
    return _string(value) or None


def _valid_source_url(value: Any) -> str | None:
    text = _string(value)
    return text if text.startswith(("https://sam.gov/", "https://www.sam.gov/")) else None


def _date_or_none(value: Any) -> date | None:
    text = _string(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _datetime_or_none(value: Any) -> datetime | None:
    text = _string(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _digits_or_none(value: Any, *, maximum: int) -> str | None:
    text = _string(value)
    return text if text.isdigit() and 2 <= len(text) <= maximum else None


def _bool_or_none(value: Any) -> bool | None:
    text = _string(value).casefold()
    if text in {"yes", "true", "active", "1"}:
        return True
    if text in {"no", "false", "inactive", "0"}:
        return False
    return None


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError) as exc:
        raise SamError("SAM.gov returned an invalid totalRecords value") from exc


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _retry_after_seconds(response: httpx.Response) -> int:
    try:
        return max(1, int(response.headers.get("Retry-After", "60")))
    except ValueError:
        return 60
