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


def _client(
    *,
    sam_api_key: str | None = "sam-key",
    api_keys: frozenset[str] = frozenset({"test-key"}),
    rapidapi_proxy_secret: str | None = None,
    rate_limit_per_minute: int = 10,
    sam_daily_request_budget: int = 8,
) -> TestClient:
    settings = UsSettings(
        environment="test",
        api_keys=api_keys,
        rapidapi_proxy_secret=rapidapi_proxy_secret,
        rate_limit_per_minute=rate_limit_per_minute,
        sam_api_key=sam_api_key,
        sam_daily_request_budget=sam_daily_request_budget,
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


def test_us_api_readiness_requires_sam_configuration() -> None:
    with _client() as client:
        assert client.get("/ready").status_code == 200
    with _client(sam_api_key=None) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503


def test_us_api_limits_direct_and_rapidapi_consumers() -> None:
    with _client(rate_limit_per_minute=1) as client:
        headers = {"X-API-Key": "test-key"}
        assert client.get("/v1/awards/search", headers=headers).status_code == 200
        limited = client.get("/v1/awards/search", headers=headers)
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "60"

    with _client(
        api_keys=frozenset(),
        rapidapi_proxy_secret="proxy-secret",
    ) as client:
        response = client.get(
            "/v1/awards/search",
            headers={
                "X-RapidAPI-Proxy-Secret": "proxy-secret",
                "X-RapidAPI-User": "test-consumer",
            },
        )
        assert response.status_code == 200


def test_us_api_stops_before_exceeding_sam_daily_budget() -> None:
    headers = {"X-API-Key": "test-key"}
    with _client(sam_daily_request_budget=1) as client:
        first = client.get(
            "/v1/opportunities/search", params={"q": "cloud"}, headers=headers
        )
        second = client.get(
            "/v1/opportunities/search",
            params={"q": "cybersecurity"},
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 503
    assert second.json()["detail"] == "SAM.gov daily request budget is exhausted"
    assert int(second.headers["Retry-After"]) > 0


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
