from __future__ import annotations

from datetime import date, datetime

import httpx
import pytest

from jp_business_signals.adapters.gbiz import GbizClient, transform_gbiz_company


def test_client_uses_v2_update_endpoint_and_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "hojin-infos": [{"corporate_number": "1234567890123"}],
                "pageNumber": "1",
                "totalPage": "1",
                "totalCount": "1",
            },
        )

    with GbizClient(
        token="secret-token",
        transport=httpx.MockTransport(handler),
        request_interval_seconds=0,
    ) as client:
        pages = list(
            client.iter_updated_company_pages(
                from_date=date(2026, 8, 1),
                to_date=date(2026, 8, 26),
                max_pages=5,
            )
        )

    assert pages == [[{"corporate_number": "1234567890123"}]]
    assert requests[0].url.host == "api.info.gbiz.go.jp"
    assert requests[0].url.path == "/hojin/v2/hojin/updateInfo"
    assert requests[0].url.params["from"] == "20260801"
    assert requests[0].url.params["to"] == "20260826"
    assert requests[0].headers["X-hojinInfo-api-token"] == "secret-token"


def test_client_retries_429_without_leaking_token() -> None:
    call_count = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={"hojin-infos": [], "pageNumber": "1", "totalPage": "1", "totalCount": "0"},
        )

    with GbizClient(
        token="secret-token",
        transport=httpx.MockTransport(handler),
        request_interval_seconds=0,
        sleep=delays.append,
    ) as client:
        pages = list(
            client.iter_updated_company_pages(
                from_date=date(2026, 8, 26),
                to_date=date(2026, 8, 26),
                max_pages=1,
            )
        )

    assert pages == [[]]
    assert call_count == 2
    assert delays == [0]


def test_client_uses_procurement_update_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "hojin-infos": [
                    {
                        "corporate_number": "1234567890123",
                        "procurement": [{"title": "Analysis", "date_of_order": "2026-08-26"}],
                    }
                ],
                "pageNumber": "1",
                "totalPage": "1",
                "totalCount": "1",
            },
        )

    with GbizClient(
        token="secret-token",
        transport=httpx.MockTransport(handler),
        request_interval_seconds=0,
    ) as client:
        pages = list(
            client.iter_updated_procurement_pages(
                from_date=date(2026, 8, 26),
                to_date=date(2026, 8, 26),
                max_pages=1,
            )
        )

    assert len(pages[0]) == 1
    assert requests[0].url.path == "/hojin/v2/hojin/updateInfo/procurement"


def test_transform_gbiz_company_builds_traceable_signals() -> None:
    raw = {
        "corporate_number": "1234567890123",
        "name": "試験株式会社",
        "kana": "シケン",
        "location": "東京都千代田区丸の内1-1",
        "industry": ["情報通信業"],
        "company_url": "example.jp",
        "update_date": "2026-08-20",
        "certification": [{"title": "認定"}],
        "procurement": [{"title": "分析業務", "date_of_order": "2026-08-19"}],
        "subsidy": [{"title": "研究支援", "date_of_approval": "20260818"}],
        "patent": [{"title": "解析装置", "application_date": "2026/08/17"}],
    }
    collected_at = datetime.fromisoformat("2026-08-26T12:00:00+09:00")

    company, signals = transform_gbiz_company(raw, collected_at=collected_at)

    assert company.name == "試験株式会社"
    assert company.prefecture == "東京都"
    assert company.city == "千代田区丸の内1-1"
    assert str(company.homepage_url) == "https://example.jp/"
    assert company.procurement_count == 1
    assert company.subsidy_count == 1
    assert company.patent_count == 1
    assert company.activity_score == 20
    assert {signal.signal_type for signal in signals} == {
        "profile_change",
        "procurement",
        "subsidy",
        "patent",
    }
    assert all(signal.source_name == "gBizINFO" for signal in signals)
    assert all("hojinBango=1234567890123" in str(signal.source_url) for signal in signals)


def test_transform_rejects_invalid_corporate_number() -> None:
    with pytest.raises(ValueError, match="corporate_number"):
        transform_gbiz_company({"corporate_number": "invalid"})
