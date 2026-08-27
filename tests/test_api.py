from __future__ import annotations

from fastapi.testclient import TestClient

from jp_business_signals.config import Settings
from jp_business_signals.main import create_app


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
