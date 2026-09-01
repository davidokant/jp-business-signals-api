from __future__ import annotations

from datetime import date

import httpx
import pytest

from us_federal_signals.adapters.sam import (
    SamError,
    SamOpportunitiesClient,
    SamRateLimitError,
)

SAMPLE_RESPONSE = {
    "totalRecords": 2,
    "limit": 10,
    "offset": 0,
    "opportunitiesData": [
        {
            "noticeId": "notice-123",
            "title": "Cloud migration and cybersecurity support",
            "solicitationNumber": "47QTCA-26-R-0001",
            "fullParentPathName": "GENERAL SERVICES ADMINISTRATION.FAS",
            "postedDate": "2026-08-20",
            "type": "Solicitation",
            "baseType": "Combined Synopsis/Solicitation",
            "responseDeadLine": "2026-09-15T17:00:00-04:00",
            "naicsCode": "541512",
            "classificationCode": "DA10",
            "typeOfSetAside": "SBA",
            "typeOfSetAsideDescription": "Total Small Business Set-Aside",
            "active": "Yes",
            "placeOfPerformance": {
                "city": {"name": "Washington"},
                "state": {"code": "DC"},
            },
            "uiLink": "https://sam.gov/opp/notice-123/view",
            "pointOfContact": [
                {"fullName": "Excluded Person", "email": "excluded@example.gov"}
            ],
            "description": "https://api.sam.gov/private-description-link",
        },
        {"noticeId": "missing-title"},
    ],
}


def test_sam_search_normalizes_safe_metadata_and_request_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    with SamOpportunitiesClient(
        api_key="test-sam-key", transport=httpx.MockTransport(handler)
    ) as client:
        result = client.search_opportunities(
            q="cloud",
            posted_from=date(2026, 8, 1),
            posted_to=date(2026, 8, 30),
            notice_types=["o", "k"],
            organization_name="General Services Administration",
            state="DC",
            naics_code="541512",
            classification_code="DA10",
            set_aside_code="SBA",
            limit=10,
            page=0,
        )

    request = requests[0]
    assert request.url.host == "api.sam.gov"
    assert request.url.path == "/opportunities/v2/search"
    assert request.url.params["api_key"] == "test-sam-key"
    assert request.url.params["postedFrom"] == "08/01/2026"
    assert request.url.params["postedTo"] == "08/30/2026"
    assert request.url.params.get_list("ptype") == ["o", "k"]
    assert request.url.params["organizationName"] == "General Services Administration"
    assert request.url.params["ncode"] == "541512"
    assert result.count == 2
    assert len(result.items) == 1
    opportunity = result.items[0]
    assert opportunity.notice_id == "notice-123"
    assert opportunity.naics_code == "541512"
    assert opportunity.place_of_performance_state == "DC"
    assert opportunity.active is True
    serialized = opportunity.model_dump_json()
    assert "Excluded Person" not in serialized
    assert "excluded@example.gov" not in serialized
    assert "private-description-link" not in serialized


def test_sam_search_rejects_invalid_range_without_request() -> None:
    transport = httpx.MockTransport(lambda _: pytest.fail("request not expected"))
    with SamOpportunitiesClient(api_key="key", transport=transport) as client:
        with pytest.raises(ValueError, match="one year"):
            client.search_opportunities(
                posted_from=date(2024, 1, 1),
                posted_to=date(2026, 1, 2),
            )


def test_sam_search_rejects_invalid_payload() -> None:
    with SamOpportunitiesClient(
        api_key="key",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"items": []})),
    ) as client:
        with pytest.raises(SamError, match="invalid opportunities payload"):
            client.search_opportunities(
                posted_from=date(2026, 8, 1),
                posted_to=date(2026, 8, 30),
            )


def test_sam_search_classifies_upstream_rate_limit_without_exposing_key() -> None:
    with SamOpportunitiesClient(
        api_key="test-sam-key",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(429, headers={"Retry-After": "120"})
        ),
    ) as client:
        with pytest.raises(SamRateLimitError) as captured:
            client.search_opportunities(
                posted_from=date(2026, 8, 1),
                posted_to=date(2026, 8, 30),
            )

    assert captured.value.retry_after_seconds == 120
    assert "test-sam-key" not in str(captured.value)
