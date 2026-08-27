from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Final
from xml.etree import ElementTree

import httpx
from pydantic import ValidationError

from ..schemas import TenderOpportunity, TenderSearchResponse

KKJ_SOURCE_NAME: Final = "Japan Public Procurement Information Portal (KKJ)"
KKJ_SOURCE_LICENSE: Final = (
    "KKJ Search API Terms: identify the source and link to the portal; "
    "rate limits and current terms apply"
)

PREFECTURE_CODES: Final = {
    "hokkaido": "01", "北海道": "01", "aomori": "02", "青森": "02", "青森県": "02",
    "iwate": "03", "岩手": "03", "岩手県": "03", "miyagi": "04", "宮城": "04",
    "宮城県": "04", "akita": "05", "秋田": "05", "秋田県": "05", "yamagata": "06",
    "山形": "06", "山形県": "06", "fukushima": "07", "福島": "07", "福島県": "07",
    "ibaraki": "08", "茨城": "08", "茨城県": "08", "tochigi": "09", "栃木": "09",
    "栃木県": "09", "gunma": "10", "群馬": "10", "群馬県": "10", "saitama": "11",
    "埼玉": "11", "埼玉県": "11", "chiba": "12", "千葉": "12", "千葉県": "12",
    "tokyo": "13", "東京": "13", "東京都": "13", "kanagawa": "14", "神奈川": "14",
    "神奈川県": "14", "niigata": "15", "新潟": "15", "新潟県": "15", "toyama": "16",
    "富山": "16", "富山県": "16", "ishikawa": "17", "石川": "17", "石川県": "17",
    "fukui": "18", "福井": "18", "福井県": "18", "yamanashi": "19", "山梨": "19",
    "山梨県": "19", "nagano": "20", "長野": "20", "長野県": "20", "gifu": "21",
    "岐阜": "21", "岐阜県": "21", "shizuoka": "22", "静岡": "22", "静岡県": "22",
    "aichi": "23", "愛知": "23", "愛知県": "23", "mie": "24", "三重": "24",
    "三重県": "24", "shiga": "25", "滋賀": "25", "滋賀県": "25", "kyoto": "26",
    "京都": "26", "京都府": "26", "osaka": "27", "大阪": "27", "大阪府": "27",
    "hyogo": "28", "兵庫": "28", "兵庫県": "28", "nara": "29", "奈良": "29",
    "奈良県": "29", "wakayama": "30", "和歌山": "30", "和歌山県": "30",
    "tottori": "31", "鳥取": "31", "鳥取県": "31", "shimane": "32", "島根": "32",
    "島根県": "32", "okayama": "33", "岡山": "33", "岡山県": "33", "hiroshima": "34",
    "広島": "34", "広島県": "34", "yamaguchi": "35", "山口": "35", "山口県": "35",
    "tokushima": "36", "徳島": "36", "徳島県": "36", "kagawa": "37", "香川": "37",
    "香川県": "37", "ehime": "38", "愛媛": "38", "愛媛県": "38", "kochi": "39",
    "高知": "39", "高知県": "39", "fukuoka": "40", "福岡": "40", "福岡県": "40",
    "saga": "41", "佐賀": "41", "佐賀県": "41", "nagasaki": "42", "長崎": "42",
    "長崎県": "42", "kumamoto": "43", "熊本": "43", "熊本県": "43", "oita": "44",
    "大分": "44", "大分県": "44", "miyazaki": "45", "宮崎": "45", "宮崎県": "45",
    "kagoshima": "46", "鹿児島": "46", "鹿児島県": "46", "okinawa": "47",
    "沖縄": "47", "沖縄県": "47",
}
CATEGORY_CODES: Final = {"goods": "1", "construction": "2", "services": "3"}


class KkjError(RuntimeError):
    """Raised when the official tender source is unavailable or invalid."""


class KkjClient:
    def __init__(
        self,
        *,
        base_url: str = "https://www.kkj.go.jp/api/",
        timeout_seconds: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={
                "Accept": "application/xml, text/xml;q=0.9",
                "User-Agent": "jp-business-signals-api/0.1",
            },
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    def __enter__(self) -> KkjClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def search_tenders(
        self,
        *,
        q: str,
        buyer: str | None = None,
        prefecture: str | None = None,
        category: str | None = None,
        published_from: date | None = None,
        published_to: date | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> TenderSearchResponse:
        if published_from and published_to and published_from > published_to:
            raise ValueError("published_from must be on or before published_to")
        if limit < 1 or offset < 0 or limit + offset > 1000:
            raise ValueError("The official source supports at most 1,000 results per search")

        params = {"Query": q, "Count": str(limit + offset)}
        if buyer:
            params["Organization_Name"] = buyer
        if prefecture:
            params["LG_Code"] = _prefecture_code(prefecture)
        if category:
            params["Category"] = _category_code(category)
        if published_from or published_to:
            params["CFT_Issue_Date"] = _date_period(published_from, published_to)

        try:
            response = self._client.get("", params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise KkjError("Official tender source request failed") from exc
        return _parse_response(response.content, limit=limit, offset=offset)


def _parse_response(content: bytes, *, limit: int, offset: int) -> TenderSearchResponse:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise KkjError("Official tender source returned invalid XML") from exc
    if _text(root.find("Error")):
        raise KkjError("Official tender source returned an error")
    search_results = root.find("SearchResults")
    if search_results is None:
        raise KkjError("Official tender source response does not contain search results")
    total = _nonnegative_int(_text(search_results.find("SearchHits")))
    collected_at = datetime.now(tz=UTC)
    records: list[TenderOpportunity] = []
    for result in search_results.findall("SearchResult"):
        try:
            records.append(_to_tender(result, collected_at=collected_at))
        except ValidationError:
            # The official feed occasionally contains an incomplete or invalid
            # external-document URL. Do not expose a record without a safe,
            # traceable source link, but keep the rest of the search usable.
            continue
    return TenderSearchResponse(
        items=records[offset : offset + limit], count=total, limit=limit, offset=offset
    )


def _to_tender(result: ElementTree.Element, *, collected_at: datetime) -> TenderOpportunity:
    source_url = _text(result.find("ExternalDocumentURI"))
    tender_id = _text(result.find("Key"))
    title = _text(result.find("ProjectName"))
    if not source_url or not tender_id or not title:
        raise KkjError("Official tender result is missing a required safe metadata field")
    qualifications = _text(result.find("Certification"))
    return TenderOpportunity(
        tender_id=tender_id,
        title_ja=title,
        buyer=_text(result.find("OrganizationName")) or None,
        prefecture=_text(result.find("PrefectureName")) or None,
        city=_text(result.find("CityName")) or None,
        category=_text(result.find("Category")) or None,
        procedure_type=_text(result.find("ProcedureType")) or None,
        qualification=qualifications.split() if qualifications else [],
        published_at=_datetime_or_none(_text(result.find("CftIssueDate"))),
        tender_submission_deadline=_datetime_or_none(
            _text(result.find("TenderSubmissionDeadline"))
        ),
        opening_tenders_at=_datetime_or_none(_text(result.find("OpeningTendersEvent"))),
        delivery_due_at=_datetime_or_none(_text(result.find("PeriodEndTime"))),
        source_name=KKJ_SOURCE_NAME,
        source_url=source_url,
        source_license=KKJ_SOURCE_LICENSE,
        collected_at=collected_at,
    )


def _prefecture_code(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.isdigit() and len(normalized) == 2 and 1 <= int(normalized) <= 47:
        return normalized
    try:
        return PREFECTURE_CODES[normalized]
    except KeyError as exc:
        raise ValueError(
            "prefecture must be a Japanese/English prefecture name or JIS code"
        ) from exc


def _category_code(value: str) -> str:
    try:
        return CATEGORY_CODES[value.strip().lower()]
    except KeyError as exc:
        raise ValueError("category must be one of: goods, construction, services") from exc


def _date_period(from_date: date | None, to_date: date | None) -> str:
    start = from_date.isoformat() if from_date else ""
    end = to_date.isoformat() if to_date else ""
    return f"{start}/{end}" if start != end else start


def _datetime_or_none(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _nonnegative_int(value: str) -> int:
    try:
        return max(0, int(value))
    except ValueError as exc:
        raise KkjError("Official tender source returned an invalid result count") from exc


def _text(element: ElementTree.Element | None) -> str:
    return element.text.strip() if element is not None and element.text else ""
