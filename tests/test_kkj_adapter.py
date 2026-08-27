from __future__ import annotations

from datetime import date

import httpx
import pytest

from jp_business_signals.adapters.kkj import KkjClient, KkjError

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<Results><Version>1.0</Version><SearchResults><SearchHits>3</SearchHits>
<SearchResult><Key>abc123</Key><ExternalDocumentURI>https://example.gov.jp/tender/1</ExternalDocumentURI>
<ProjectName>クラウド移行業務</ProjectName><PrefectureName>東京都</PrefectureName>
<OrganizationName>デジタル庁</OrganizationName><Category>役務</Category><ProcedureType>一般競争入札</ProcedureType>
<Certification>A B</Certification><CftIssueDate>2026-08-24T00:00:00+09:00</CftIssueDate>
<TenderSubmissionDeadline>2026-09-14T17:00:00+09:00</TenderSubmissionDeadline>
<ProjectDescription>連絡先は架空太郎</ProjectDescription></SearchResult></SearchResults></Results>""".encode()


def test_search_normalizes_safe_official_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=SAMPLE_XML, headers={"content-type": "application/xml"})

    with KkjClient(transport=httpx.MockTransport(handler)) as client:
        result = client.search_tenders(
            q="cloud",
            buyer="Digital Agency",
            prefecture="Tokyo",
            category="services",
            published_from=date(2026, 8, 1),
            published_to=date(2026, 8, 31),
            limit=10,
            offset=0,
        )

    assert requests[0].url.host == "www.kkj.go.jp"
    assert requests[0].url.path == "/api/"
    assert requests[0].url.params["Query"] == "cloud"
    assert requests[0].url.params["Organization_Name"] == "Digital Agency"
    assert requests[0].url.params["LG_Code"] == "13"
    assert requests[0].url.params["Category"] == "3"
    assert requests[0].url.params["CFT_Issue_Date"] == "2026-08-01/2026-08-31"
    assert result.count == 3
    assert result.items[0].title_ja == "クラウド移行業務"
    assert result.items[0].qualification == ["A", "B"]
    assert str(result.items[0].source_url) == "https://example.gov.jp/tender/1"
    assert "ProjectDescription" not in result.items[0].model_dump_json()


def test_search_rejects_unknown_prefecture_without_request() -> None:
    transport = httpx.MockTransport(lambda _: pytest.fail("request not expected"))
    with KkjClient(transport=transport) as client:
        with pytest.raises(ValueError, match="prefecture"):
            client.search_tenders(
                q="cloud",
                buyer=None,
                prefecture="Atlantis",
                category=None,
                published_from=None,
                published_to=None,
                limit=10,
                offset=0,
            )


def test_search_rejects_source_errors() -> None:
    with KkjClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"<Results><Error>busy</Error></Results>")
        )
    ) as client:
        with pytest.raises(KkjError, match="returned an error"):
            client.search_tenders(
                q="cloud",
                buyer=None,
                prefecture=None,
                category=None,
                published_from=None,
                published_to=None,
                limit=10,
                offset=0,
            )
