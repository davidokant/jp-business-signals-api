from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from ..schemas import FederalContractAward, FederalContractAwardSearchResponse

USASPENDING_SOURCE_NAME: Final = "USAspending.gov"
USASPENDING_SOURCE_LICENSE: Final = (
    "Official USAspending API; source repository and API contracts are released under CC0"
)
CONTRACT_AWARD_TYPE_CODES: Final = ["A", "B", "C", "D"]
AWARD_FIELDS: Final = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Start Date",
    "End Date",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Description",
    "NAICS",
    "PSC",
]


class UsaspendingError(RuntimeError):
    """Raised when USAspending is unavailable or returns invalid data."""


class UsaspendingClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.usaspending.gov",
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "us-federal-signals-feasibility/0.1",
            },
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    def __enter__(self) -> UsaspendingClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def search_contract_awards(
        self,
        *,
        start_date: date,
        end_date: date,
        keywords: list[str] | None = None,
        agency: str | None = None,
        naics_codes: list[str] | None = None,
        psc_codes: list[str] | None = None,
        set_aside_codes: list[str] | None = None,
        recipient_names: list[str] | None = None,
        limit: int = 25,
        page: int = 1,
    ) -> FederalContractAwardSearchResponse:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if page < 1:
            raise ValueError("page must be at least 1")
        filters: dict[str, Any] = {
            "award_type_codes": CONTRACT_AWARD_TYPE_CODES,
            "time_period": [
                {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                }
            ],
        }
        if keywords:
            filters["keywords"] = keywords
        if agency:
            filters["agencies"] = [
                {"type": "awarding", "tier": "toptier", "name": agency}
            ]
        if naics_codes:
            filters["naics_codes"] = {"require": naics_codes}
        if psc_codes:
            filters["psc_codes"] = {"require": psc_codes}
        if set_aside_codes:
            filters["set_aside_type_codes"] = set_aside_codes
        if recipient_names:
            filters["recipient_search_text"] = recipient_names
        request_payload = {
            "spending_level": "awards",
            "filters": filters,
            "fields": AWARD_FIELDS,
            "sort": "End Date",
            "order": "desc",
            "limit": limit,
            "page": page,
        }
        try:
            response = self._client.post(
                "/api/v2/search/spending_by_award/", json=request_payload
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise UsaspendingError("USAspending contract-award request failed") from exc
        return _parse_response(payload, page=page, limit=limit)


def _parse_response(
    payload: Any, *, page: int, limit: int
) -> FederalContractAwardSearchResponse:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise UsaspendingError("USAspending returned an invalid award payload")
    collected_at = datetime.now(UTC)
    items: list[FederalContractAward] = []
    for raw in payload["results"]:
        if not isinstance(raw, dict):
            continue
        try:
            items.append(_to_award(raw, collected_at=collected_at))
        except (UsaspendingError, ValidationError):
            continue
    metadata = payload.get("page_metadata")
    has_next = bool(metadata.get("hasNext")) if isinstance(metadata, dict) else False
    return FederalContractAwardSearchResponse(
        items=items,
        count=len(items),
        page=page,
        limit=limit,
        has_next=has_next,
    )


def _to_award(raw: dict[str, Any], *, collected_at: datetime) -> FederalContractAward:
    award_id = _string(raw.get("Award ID"))
    if not award_id:
        raise UsaspendingError("USAspending award is missing Award ID")
    generated_id = _string(raw.get("generated_internal_id"))
    source_identifier = generated_id or award_id
    naics_code, naics_description = _code_and_description(raw.get("NAICS"))
    psc_code, psc_description = _code_and_description(raw.get("PSC"))
    return FederalContractAward(
        award_id=award_id,
        recipient_name=_string(raw.get("Recipient Name")) or None,
        recipient_uei=_string(raw.get("Recipient UEI")) or None,
        start_date=_date_or_none(raw.get("Start Date")),
        end_date=_date_or_none(raw.get("End Date")),
        award_amount=_decimal_or_none(raw.get("Award Amount")),
        awarding_agency=_string(raw.get("Awarding Agency")) or None,
        awarding_sub_agency=_string(raw.get("Awarding Sub Agency")) or None,
        description=_string(raw.get("Description")) or None,
        naics_code=naics_code,
        naics_description=naics_description,
        psc_code=psc_code,
        psc_description=psc_description,
        source_name=USASPENDING_SOURCE_NAME,
        source_url=f"https://www.usaspending.gov/award/{quote(source_identifier, safe='')}/",
        source_license=USASPENDING_SOURCE_LICENSE,
        collected_at=collected_at,
    )


def _code_and_description(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, dict):
        return (
            _string(value.get("code")) or None,
            _string(value.get("description")) or None,
        )
    text = _string(value)
    return (text or None, None)


def _date_or_none(value: Any) -> date | None:
    text = _string(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
