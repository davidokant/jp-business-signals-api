from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from datetime import date, datetime, timedelta, timezone
from datetime import time as datetime_time
from typing import Any
from urllib.parse import urlparse

import httpx

from ..schemas import Company, Signal
from ..scoring import calculate_activity_score

GBIZ_SOURCE_NAME = "gBizINFO"
GBIZ_SOURCE_LICENSE = (
    "gBizINFO API/Data Download Terms; commercial use permitted; "
    "current terms must be checked before redistribution"
)
GBIZ_TERMS_URL = (
    "https://help.info.gbiz.go.jp/hc/ja/articles/"
    "4999421139102-API-%E3%83%87%E3%83%BC%E3%82%BF"
    "%E3%83%80%E3%82%A6%E3%83%B3%E3%83%AD%E3%83%BC%E3%83%89"
    "%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84"
)
JST = timezone(timedelta(hours=9))
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
PREFECTURES = (
    "Hokkaido",
    "Aomori",
    "Iwate",
    "Miyagi",
    "Akita",
    "Yamagata",
    "Fukushima",
    "Ibaraki",
    "Tochigi",
    "Gunma",
    "Saitama",
    "Chiba",
    "Tokyo",
    "Kanagawa",
    "Niigata",
    "Toyama",
    "Ishikawa",
    "Fukui",
    "Yamanashi",
    "Nagano",
    "Gifu",
    "Shizuoka",
    "Aichi",
    "Mie",
    "Shiga",
    "Kyoto",
    "Osaka",
    "Hyogo",
    "Nara",
    "Wakayama",
    "Tottori",
    "Shimane",
    "Okayama",
    "Hiroshima",
    "Yamaguchi",
    "Tokushima",
    "Kagawa",
    "Ehime",
    "Kochi",
    "Fukuoka",
    "Saga",
    "Nagasaki",
    "Kumamoto",
    "Oita",
    "Miyazaki",
    "Kagoshima",
    "Okinawa",
    "北海道",
    "青森県",
    "岩手県",
    "宮城県",
    "秋田県",
    "山形県",
    "福島県",
    "茨城県",
    "栃木県",
    "群馬県",
    "埼玉県",
    "千葉県",
    "東京都",
    "神奈川県",
    "新潟県",
    "富山県",
    "石川県",
    "福井県",
    "山梨県",
    "長野県",
    "岐阜県",
    "静岡県",
    "愛知県",
    "三重県",
    "滋賀県",
    "京都府",
    "大阪府",
    "兵庫県",
    "奈良県",
    "和歌山県",
    "鳥取県",
    "島根県",
    "岡山県",
    "広島県",
    "山口県",
    "徳島県",
    "香川県",
    "愛媛県",
    "高知県",
    "福岡県",
    "佐賀県",
    "長崎県",
    "熊本県",
    "大分県",
    "宮崎県",
    "鹿児島県",
    "沖縄県",
)


class GbizError(RuntimeError):
    """Raised when gBizINFO cannot be queried or returns an invalid payload."""


class GbizClient:
    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://api.info.gbiz.go.jp/hojin",
        timeout_seconds: float = 30.0,
        request_interval_seconds: float = 0.25,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not token.strip():
            raise ValueError("A gBizINFO API token is required")
        self.request_interval_seconds = max(0.0, request_interval_seconds)
        self.max_retries = max(0, max_retries)
        self.sleep = sleep
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "X-hojinInfo-api-token": token,
                "User-Agent": "jp-business-signals-api/0.1",
                "Accept": "application/json",
            },
            timeout=timeout_seconds,
            transport=transport,
        )

    def __enter__(self) -> GbizClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def iter_updated_company_pages(
        self,
        *,
        from_date: date,
        to_date: date,
        max_pages: int,
    ) -> Iterator[list[dict[str, Any]]]:
        if from_date > to_date:
            raise ValueError("from_date must be on or before to_date")
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        yield from self._iter_updated_pages(
            path="/v2/hojin/updateInfo",
            from_date=from_date,
            to_date=to_date,
            max_pages=max_pages,
        )

    def iter_updated_procurement_pages(
        self,
        *,
        from_date: date,
        to_date: date,
        max_pages: int,
    ) -> Iterator[list[dict[str, Any]]]:
        if from_date > to_date:
            raise ValueError("from_date must be on or before to_date")
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        yield from self._iter_updated_pages(
            path="/v2/hojin/updateInfo/procurement",
            from_date=from_date,
            to_date=to_date,
            max_pages=max_pages,
        )

    def _iter_updated_pages(
        self,
        *,
        path: str,
        from_date: date,
        to_date: date,
        max_pages: int,
    ) -> Iterator[list[dict[str, Any]]]:
        page = 1
        while page <= max_pages:
            payload = self._request_json(
                path,
                params={
                    "from": from_date.strftime("%Y%m%d"),
                    "to": to_date.strftime("%Y%m%d"),
                    "page": str(page),
                    "metadata_flg": "true",
                },
            )
            records = payload.get("hojin-infos", [])
            if not isinstance(records, list):
                raise GbizError("gBizINFO response field 'hojin-infos' is not a list")
            yield [record for record in records if isinstance(record, dict)]

            total_pages = _positive_int(payload.get("totalPage"), default=page)
            if page >= total_pages:
                break
            page += 1
            if self.request_interval_seconds:
                self.sleep(self.request_interval_seconds)

    def _request_json(self, path: str, *, params: Mapping[str, str]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            response: httpx.Response | None = None
            try:
                response = self._client.get(path, params=params)
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise GbizError("gBizINFO returned a non-object JSON payload")
                    errors = payload.get("errors")
                    if errors:
                        raise GbizError(f"gBizINFO returned API errors: {errors!r}")
                    return payload
            except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
                last_error = exc

            if attempt >= self.max_retries:
                break
            self.sleep(_retry_delay(response, attempt))

        if isinstance(last_error, httpx.HTTPStatusError):
            status_code = last_error.response.status_code
            raise GbizError(f"gBizINFO request failed with HTTP {status_code}") from last_error
        if response is not None:
            raise GbizError(f"gBizINFO request failed with HTTP {response.status_code}")
        raise GbizError("gBizINFO request failed") from last_error


def transform_gbiz_company(
    raw: Mapping[str, Any],
    *,
    collected_at: datetime | None = None,
) -> tuple[Company, list[Signal]]:
    collected = collected_at or datetime.now(tz=JST)
    corporate_number = _clean_text(raw.get("corporate_number"))
    if len(corporate_number) != 13 or not corporate_number.isdigit():
        raise ValueError("gBizINFO record has an invalid corporate_number")

    name = _clean_text(raw.get("name")) or _clean_text(raw.get("name_en"))
    if not name:
        name = corporate_number
    location = _clean_text(raw.get("location"))
    prefecture, city = split_location(location)
    procurement = _list_of_mappings(raw.get("procurement"))
    subsidy = _list_of_mappings(raw.get("subsidy"))
    patent = _list_of_mappings(raw.get("patent"))
    certification = _list_of_mappings(raw.get("certification"))
    industries = raw.get("industry")
    industry = (
        ", ".join(_clean_text(item) for item in industries if _clean_text(item))
        if isinstance(industries, list)
        else _clean_text(industries) or None
    )
    source_url = f"https://info.gbiz.go.jp/hojin/ichiran?hojinBango={corporate_number}"
    updated_at = _parse_datetime(raw.get("update_date"))

    company = Company(
        corporate_number=corporate_number,
        name=name,
        name_kana=_clean_text(raw.get("kana")) or None,
        prefecture=prefecture,
        city=city,
        industry=industry,
        homepage_url=_normalize_url(raw.get("company_url")),
        activity_score=calculate_activity_score(
            procurement_count=len(procurement),
            subsidy_count=len(subsidy),
            patent_count=len(patent),
            certification_count=len(certification),
        ),
        procurement_count=len(procurement),
        subsidy_count=len(subsidy),
        patent_count=len(patent),
        source_name=GBIZ_SOURCE_NAME,
        source_url=source_url,
        source_license=GBIZ_SOURCE_LICENSE,
        source_updated_at=updated_at,
        collected_at=collected,
    )

    signals: list[Signal] = []
    profile_date = _parse_date(raw.get("update_date"))
    if profile_date:
        signals.append(
            _signal(
                corporate_number=corporate_number,
                signal_type="profile_change",
                title="Company profile updated in gBizINFO",
                occurred_on=profile_date,
                score_delta=1,
                source_url=source_url,
                collected_at=collected,
            )
        )
    signals.extend(
        _child_signals(
            corporate_number=corporate_number,
            signal_type="procurement",
            records=procurement,
            date_field="date_of_order",
            title_prefix="Public procurement",
            score_delta=5,
            source_url=source_url,
            collected_at=collected,
        )
    )
    signals.extend(
        _child_signals(
            corporate_number=corporate_number,
            signal_type="subsidy",
            records=subsidy,
            date_field="date_of_approval",
            title_prefix="Subsidy",
            score_delta=3,
            source_url=source_url,
            collected_at=collected,
        )
    )
    signals.extend(
        _child_signals(
            corporate_number=corporate_number,
            signal_type="patent",
            records=patent,
            date_field="application_date",
            title_prefix="Patent activity",
            score_delta=2,
            source_url=source_url,
            collected_at=collected,
        )
    )
    return company, signals


def split_location(location: str) -> tuple[str | None, str | None]:
    cleaned = location.strip()
    if not cleaned:
        return None, None
    for prefecture in sorted(PREFECTURES, key=len, reverse=True):
        if cleaned.startswith(prefecture):
            remainder = cleaned[len(prefecture) :].lstrip(" ,")
            return prefecture, remainder or None
    return None, cleaned


def _child_signals(
    *,
    corporate_number: str,
    signal_type: str,
    records: list[Mapping[str, Any]],
    date_field: str,
    title_prefix: str,
    score_delta: int,
    source_url: str,
    collected_at: datetime,
) -> list[Signal]:
    signals: list[Signal] = []
    for record in records:
        occurred_on = _parse_date(record.get(date_field))
        if not occurred_on:
            continue
        item_title = _clean_text(record.get("title")) or "Untitled record"
        signals.append(
            _signal(
                corporate_number=corporate_number,
                signal_type=signal_type,
                title=f"{title_prefix}: {item_title}"[:500],
                occurred_on=occurred_on,
                score_delta=score_delta,
                source_url=source_url,
                collected_at=collected_at,
            )
        )
    return signals


def _signal(
    *,
    corporate_number: str,
    signal_type: str,
    title: str,
    occurred_on: date,
    score_delta: int,
    source_url: str,
    collected_at: datetime,
) -> Signal:
    return Signal(
        corporate_number=corporate_number,
        signal_type=signal_type,
        title=title,
        occurred_on=occurred_on,
        score_delta=score_delta,
        source_name=GBIZ_SOURCE_NAME,
        source_url=source_url,
        source_license=GBIZ_SOURCE_LICENSE,
        collected_at=collected_at,
    )


def _clean_text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _list_of_mappings(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _normalize_url(value: object) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    if not urlparse(cleaned).scheme:
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    return cleaned if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _parse_date(value: object) -> date | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    normalized = cleaned.replace("/", "-").replace(".", "-")
    formats = ("%Y-%m-%d", "%Y%m%d", "%Y-%m", "%Y%m")
    for format_string in formats:
        try:
            parsed = datetime.strptime(normalized, format_string).date()
            return parsed.replace(day=1) if format_string in {"%Y-%m", "%Y%m"} else parsed
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _parse_datetime(value: object) -> datetime | None:
    parsed_date = _parse_date(value)
    if not parsed_date:
        return None
    return datetime.combine(parsed_date, datetime_time.min, tzinfo=JST)


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(60.0, max(0.0, float(retry_after)))
            except ValueError:
                pass
    return min(30.0, 0.5 * (2**attempt))
