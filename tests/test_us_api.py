from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from us_federal_signals.config import UsSettings
from us_federal_signals.main import create_app
from us_federal_signals.schemas import (
    FederalContractAward,
    FederalContractAwardSearchResponse,
    FederalOpportunity,
    FederalOpportunitySearchResponse,
)


class _ContextClient:
    def __enter__(self) -> Any:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class FakeSamClient(_ContextClient):
    calls: list[dict[str, Any]] = []

    def search_opportunities(self, **kwargs: Any) -> FederalOpportunitySearchResponse:
        self.calls.append(kwargs)
        return FederalOpportunitySearchResponse(
            items=[
                FederalOpportunity(
                    notice_id="notice-123",
                    title=f"Cloud support for {kwargs.get('q')}",
                    organization_name="General Services Administration",
                    notice_type="Solicitation",
                    posted_date=date.today(),
                    response_deadline=datetime.now(UTC) + timedelta(days=20),
                    naics_code="541512",
                    classification_code="DA10",
                    source_name="SAM.gov Contract Opportunities",
                    source_url="https://sam.gov/opp/notice-123/view",
                    source_license="Official API terms apply",
                    collected_at=datetime.now(UTC),
                )
            ],
            count=1,
            limit=kwargs["limit"],
            page=kwargs["page"],
        )


class FakeUsaspendingClient(_ContextClient):
    def search_contract_awards(self, **kwargs: Any) -> FederalContractAwardSearchResponse:
        return FederalContractAwardSearchResponse(
            items=[
                FederalContractAward(
                    award_id="47QTCA26F0001",
                    recipient_name="Example Cloud LLC",
                    end_date=date(2026, 9, 30),
                    source_name="USAspending.gov",
                    source_url=(
                        "https://www.usaspending.gov/award/CONT_AWD_47QTCA26F0001/"
                    ),
                    source_license="Official source",
                    collected_at=datetime.now(UTC),
                )
            ],
            count=1,
            page=kwargs["page"],
            limit=kwargs["limit"],
            has_next=False,
        )


def _factory(client_type: type[_ContextClient]):
    return lambda **_: client_type()


def _client(*, sam_api_key: str | None = "sam-key") -> TestClient:
    settings = UsSettings(
        environment="test",
        api_keys=frozenset({"test-key"}),
        sam_api_key=sam_api_key,
    )
    return TestClient(
        create_app(
            settings,
            sam_client_factory=_factory(FakeSamClient),
            usaspending_client_factory=_factory(FakeUsaspendingClient),
        )
    )


def test_us_api_requires_customer_key_and_configured_sam_source() -> None:
    with _client() as client:
        assert client.get("/v1/opportunities/search").status_code == 401
    with _client(sam_api_key=None) as client:
        response = client.get(
            "/v1/opportunities/search", headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 503


def test_us_api_exposes_opportunities_awards_and_supplier_fit() -> None:
    FakeSamClient.calls.clear()
    headers = {"X-API-Key": "test-key"}
    with _client() as client:
        opportunities = client.get(
            "/v1/opportunities/search", params={"q": "cloud"}, headers=headers
        )
        awards = client.get(
            "/v1/awards/search", params={"q": "cloud"}, headers=headers
        )
        fit = client.post(
            "/v1/supplier-fit-analysis",
            headers=headers,
            json={
                "capabilities": ["cloud", "cybersecurity"],
                "naics_codes": ["541512"],
                "psc_codes": ["DA10"],
            },
        )

    assert opportunities.status_code == 200
    assert opportunities.json()["items"][0]["notice_id"] == "notice-123"
    assert awards.status_code == 200
    assert awards.json()["items"][0]["award_id"] == "47QTCA26F0001"
    assert fit.status_code == 200
    assert fit.json()["count"] == 1
    assert fit.json()["items"][0]["naics_fit"] == "matched"
    assert len(FakeSamClient.calls) == 3
