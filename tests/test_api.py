from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from jp_business_signals.config import Settings
from jp_business_signals.main import create_app
from jp_business_signals.schemas import TenderOpportunity, TenderSearchResponse


class FakeKkjClient:
    def __init__(self, **_: object) -> None:
        pass

    def __enter__(self) -> FakeKkjClient:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def search_tenders(
        self,
        *,
        q: str,
        buyer: str | None = None,
        limit: int = 25,
        offset: int = 0,
        **_: object,
    ) -> TenderSearchResponse:
        now = datetime.now(UTC)
        items = [
            TenderOpportunity(
                tender_id="official-001",
                title_ja="クラウド基盤セキュリティ運用",
                buyer=buyer or "デジタル庁",
                prefecture="東京都",
                city="千代田区",
                category="services",
                procedure_type="open tender",
                qualification=["A"],
                published_at=now - timedelta(days=1),
                tender_submission_deadline=now + timedelta(days=5),
                source_name="KKJ",
                source_url="https://example.gov.jp/tenders/1",
                source_license="Official source terms",
                collected_at=now,
            ),
            TenderOpportunity(
                tender_id="official-002",
                title_ja="行政データ分析業務",
                buyer=buyer or "デジタル庁",
                prefecture="大阪府",
                city="大阪市",
                category="consulting",
                procedure_type="open tender",
                qualification=[],
                published_at=now - timedelta(days=2),
                tender_submission_deadline=now + timedelta(days=40),
                source_name="KKJ",
                source_url="https://example.gov.jp/tenders/2",
                source_license="Official source terms",
                collected_at=now,
            ),
        ]
        return TenderSearchResponse(
            items=items[offset : offset + limit],
            count=len(items),
            limit=limit,
            offset=offset,
        )


def test_health_is_public(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_public_data_status_reports_coverage_without_authentication(client) -> None:
    response = client.get("/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["companies"] == 4
    assert payload["signals"] == 4
    assert payload["official_sources"] == 1
    assert payload["latest_collection"] is not None


def test_internal_refresh_requires_its_own_secret_and_returns_status(tmp_path, monkeypatch) -> None:
    settings = Settings(
        environment="test",
        database_path=tmp_path / "refresh.db",
        api_keys=frozenset({"test-key"}),
        rapidapi_proxy_secret=None,
        rate_limit_per_minute=100,
        auto_seed_sample=True,
        refresh_token="refresh-secret",
    )
    monkeypatch.setattr("jp_business_signals.main.refresh_gbiz_database", lambda _: None)
    with TestClient(create_app(settings)) as test_client:
        assert test_client.post("/internal/refresh-gbiz").status_code == 404
        response = test_client.post(
            "/internal/refresh-gbiz", headers={"X-Refresh-Token": "refresh-secret"}
        )
    assert response.status_code == 200
    assert response.json()["companies"] == 4


def test_landing_page_is_public(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Japan procurement signals," in response.text
    assert "ready for code." in response.text
    assert 'content="/assets/jp-signals-og.png"' in response.text

    preview = client.get("/assets/jp-signals-og.png")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"


def test_public_launch_information_pages_are_available(client) -> None:
    for path, expected_text in (
        ("/privacy", "Privacy, plainly."),
        ("/terms", "Use data responsibly."),
        ("/data-sources", "Trace every signal."),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert expected_text in response.text


def test_demo_stats_are_public(client) -> None:
    response = client.get("/demo/stats")
    assert response.status_code == 200
    assert response.json() == {
        "companies": 4,
        "procurement_signals": 1,
        "active_companies": 4,
        "official_sources": 1,
    }


def test_demo_procurement_search_is_public(client) -> None:
    response = client.get("/demo/signals", params={"q": "Sakura"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["corporate_number"] == "0000000000001"
    assert payload["items"][0]["company_name"] == "Sakura Industrial Systems (Synthetic)"


def test_demo_procurement_search_returns_empty_for_no_match(client) -> None:
    response = client.get("/demo/signals", params={"q": "NoSuchCompany"})
    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}


def test_company_routes_require_authentication(client) -> None:
    response = client.get("/v1/companies/search")
    assert response.status_code == 401


def test_search_filters_and_orders_by_activity(client, auth_headers) -> None:
    response = client.get(
        "/v1/companies/search",
        params={"min_activity_score": 60},
        headers=auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 3
    assert [item["activity_score"] for item in payload["items"]] == [91, 82, 68]


def test_get_company_and_timeline(client, auth_headers) -> None:
    company_number = "0000000000001"
    company = client.get(f"/v1/companies/{company_number}", headers=auth_headers)
    timeline = client.get(f"/v1/companies/{company_number}/timeline", headers=auth_headers)
    company_by_query = client.get(
        "/v1/company-details",
        params={"corporate_number": company_number},
        headers=auth_headers,
    )
    timeline_by_query = client.get(
        "/v1/company-timeline",
        params={"corporate_number": company_number},
        headers=auth_headers,
    )

    assert company.status_code == 200
    assert company.json()["corporate_number"] == company_number
    assert timeline.status_code == 200
    assert len(timeline.json()["items"]) == 2
    assert company_by_query.status_code == 200
    assert company_by_query.json()["corporate_number"] == company_number
    assert timeline_by_query.status_code == 200
    assert len(timeline_by_query.json()["items"]) == 2


def test_signal_filters(client, auth_headers) -> None:
    response = client.get(
        "/v1/signals",
        params={"since": "2026-08-19", "signal_type": "procurement"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["signal_type"] == "procurement"


def test_procurement_signal_feed_adds_supplier_context(client, auth_headers) -> None:
    response = client.get(
        "/v1/procurement-signals",
        params={"since": "2026-08-19", "q": "award", "prefecture": "Tokyo"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["signal_type"] == "procurement"
    assert item["company_name"] == "Sakura Industrial Systems (Synthetic)"
    assert item["prefecture"] == "Tokyo"
    assert item["source_url"]


def test_tender_search_stays_disabled_until_source_confirmation(client, auth_headers) -> None:
    response = client.get("/v1/tenders/search", params={"q": "cloud"}, headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["detail"] == "Tender opportunity source is not enabled yet"


def test_company_tender_matching_stays_disabled_until_source_confirmation(
    client, auth_headers
) -> None:
    response = client.get(
        "/v1/company-tender-matches",
        params={"corporate_number": "0000000000001", "q": "cloud"},
        headers=auth_headers,
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Tender opportunity source is not enabled yet"


def test_tender_intelligence_chain_is_source_linked_and_machine_readable(
    tmp_path, monkeypatch
) -> None:
    settings = Settings(
        environment="test",
        database_path=tmp_path / "enabled.db",
        api_keys=frozenset({"test-key"}),
        rapidapi_proxy_secret=None,
        rate_limit_per_minute=100,
        auto_seed_sample=True,
        kkj_api_enabled=True,
        kkj_request_interval_seconds=0,
    )
    monkeypatch.setattr("jp_business_signals.main.KkjClient", FakeKkjClient)
    headers = {"X-API-Key": "test-key"}
    with TestClient(create_app(settings)) as test_client:
        fit = test_client.post(
            "/v1/tender-fit-analysis",
            headers=headers,
            json={
                "supplier_name": "Example Cloud Supplier",
                "capabilities": ["cloud services"],
                "preferred_prefectures": ["Tokyo"],
                "held_qualifications": ["A"],
                "excluded_keywords": ["construction"],
                "limit": 5,
            },
        )
        assert fit.status_code == 200
        fit_payload = fit.json()
        assert "クラウド" in fit_payload["expanded_queries"]
        assert fit_payload["items"][0]["action_state"] == "review_now"
        assert fit_payload["items"][0]["qualification_fit"] == "matched"
        assert fit_payload["items"][0]["geographic_fit"] == "matched"
        assert fit_payload["items"][0]["tender"]["source_url"]

        buyer = test_client.get(
            "/v1/buyer-intelligence",
            params={"buyer": "Digital Agency", "q": "cloud services"},
            headers=headers,
        )
        assert buyer.status_code == 200
        buyer_payload = buyer.json()
        assert buyer_payload["opportunities_found"] == 2
        assert buyer_payload["urgent_opportunities"] == 1
        assert buyer_payload["top_categories"]

        demo = test_client.get(
            "/demo/tender-readiness", params={"q": "cloud services"}
        )
        assert demo.status_code == 200
        assert 1 <= demo.json()["count"] <= 3
        assert demo.json()["items"][0]["source_url"]

        changes = test_client.get(
            "/v1/tender-changes", params={"action": "new"}, headers=headers
        )
        assert changes.status_code == 200
        assert changes.json()["count"] == 2
        assert {item["action"] for item in changes.json()["items"]} == {"new"}


def test_daily_tender_refresh_uses_refresh_secret_and_persists_history(
    tmp_path, monkeypatch
) -> None:
    settings = Settings(
        environment="test",
        database_path=tmp_path / "refresh-enabled.db",
        api_keys=frozenset({"test-key"}),
        rapidapi_proxy_secret=None,
        rate_limit_per_minute=100,
        auto_seed_sample=True,
        refresh_token="refresh-secret",
        kkj_api_enabled=True,
        kkj_request_interval_seconds=0,
        tender_watch_queries=("cloud", "cybersecurity"),
    )
    monkeypatch.setattr("jp_business_signals.main.KkjClient", FakeKkjClient)
    with TestClient(create_app(settings)) as test_client:
        assert test_client.post("/internal/refresh-tenders").status_code == 404
        refresh = test_client.post(
            "/internal/refresh-tenders",
            headers={"X-Refresh-Token": "refresh-secret"},
        )
        assert refresh.status_code == 200
        assert refresh.json()["tenders_observed"] == 2
        assert refresh.json()["change_events_created"] == 2

        changes = test_client.get(
            "/v1/tender-changes", headers={"X-API-Key": "test-key"}
        )
        assert changes.json()["count"] == 2


def test_sources_report_provenance(client, auth_headers) -> None:
    response = client.get("/v1/sources", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["source_name"] == "Synthetic MVP Dataset"
    assert payload["items"][0]["record_count"] == 8


def test_rapidapi_proxy_secret_is_accepted(client) -> None:
    response = client.get(
        "/v1/companies/search",
        headers={
            "X-RapidAPI-Proxy-Secret": "rapid-secret",
            "X-RapidAPI-User": "test-consumer",
        },
    )
    assert response.status_code == 200


def test_invalid_company_number_is_rejected(client, auth_headers) -> None:
    response = client.get("/v1/companies/not-a-number", headers=auth_headers)
    assert response.status_code == 422
