from __future__ import annotations

from datetime import date

import httpx
import pytest

from us_federal_signals.adapters.usaspending import (
    UsaspendingClient,
    UsaspendingError,
)

SAMPLE_RESPONSE = {
    "spending_level": "awards",
    "limit": 10,
    "results": [
        {
            "Award ID": "47QTCA26F0001",
            "Recipient Name": "Example Cloud LLC",
            "Recipient UEI": "ABCDEF123456",
            "Start Date": "2025-10-01",
            "End Date": "2026-09-30",
            "Award Amount": 1250000.50,
            "Awarding Agency": "General Services Administration",
            "Awarding Sub Agency": "Federal Acquisition Service",
            "Description": "Cloud operations support",
            "NAICS": {"code": "541512", "description": "Computer Systems Design"},
            "PSC": {"code": "DA10", "description": "IT and Telecom"},
            "generated_internal_id": "CONT_AWD_47QTCA26F0001",
        }
    ],
    "page_metadata": {"hasNext": False},
}


def test_usaspending_search_uses_contract_filters_and_normalizes_results() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    with UsaspendingClient(transport=httpx.MockTransport(handler)) as client:
        result = client.search_contract_awards(
            start_date=date(2025, 10, 1),
            end_date=date(2026, 9, 30),
            keywords=["cloud"],
            agency="General Services Administration",
            naics_codes=["541512"],
            psc_codes=["DA10"],
            set_aside_codes=["SBA"],
            recipient_names=["Example Cloud"],
            limit=10,
            page=1,
        )

    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v2/search/spending_by_award/"
    payload = __import__("json").loads(request.content)
    assert payload["filters"]["award_type_codes"] == ["A", "B", "C", "D"]
    assert payload["filters"]["keywords"] == ["cloud"]
    assert payload["filters"]["naics_codes"] == {"require": ["541512"]}
    assert payload["filters"]["psc_codes"] == {"require": ["DA10"]}
    award = result.items[0]
    assert award.recipient_uei == "ABCDEF123456"
    assert award.naics_code == "541512"
    assert award.psc_code == "DA10"
    assert str(award.source_url).endswith("/CONT_AWD_47QTCA26F0001/")


def test_usaspending_rejects_invalid_payload() -> None:
    with UsaspendingClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": []}))
    ) as client:
        with pytest.raises(UsaspendingError, match="invalid award payload"):
            client.search_contract_awards(
                start_date=date(2026, 1, 1),
                end_date=date(2026, 8, 30),
            )
