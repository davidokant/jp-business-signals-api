from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=1, max_length=200)
    source_url: HttpUrl
    source_license: str = Field(min_length=1, max_length=500)
    collected_at: datetime


class Company(SourceRecord):
    corporate_number: str = Field(pattern=r"^\d{13}$")
    name: str = Field(min_length=1, max_length=300)
    name_kana: str | None = Field(default=None, max_length=300)
    prefecture: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    homepage_url: HttpUrl | None = None
    activity_score: int = Field(ge=0, le=100)
    procurement_count: int = Field(ge=0)
    subsidy_count: int = Field(ge=0)
    patent_count: int = Field(ge=0)
    source_updated_at: datetime | None = None


class Signal(SourceRecord):
    id: int | None = None
    corporate_number: str = Field(pattern=r"^\d{13}$")
    signal_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,49}$")
    title: str = Field(min_length=1, max_length=500)
    occurred_on: date
    score_delta: int = Field(ge=-100, le=100)


class CompanySearchResponse(BaseModel):
    items: list[Company]
    count: int
    limit: int
    offset: int


class SignalListResponse(BaseModel):
    items: list[Signal]
    count: int
    limit: int
    offset: int


class ProcurementSignal(Signal):
    """A procurement event enriched with the supplier profile needed for screening."""

    company_name: str = Field(min_length=1, max_length=300)
    prefecture: str | None = Field(default=None, max_length=100)
    industry: str | None = Field(default=None, max_length=200)
    activity_score: int = Field(ge=0, le=100)


class ProcurementSignalListResponse(BaseModel):
    items: list[ProcurementSignal]
    count: int
    limit: int
    offset: int


class TenderOpportunity(SourceRecord):
    """A safe, source-linked public tender opportunity from the KKJ portal."""

    tender_id: str = Field(min_length=1, max_length=500)
    title_ja: str = Field(min_length=1, max_length=1000)
    buyer: str | None = Field(default=None, max_length=500)
    prefecture: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    procedure_type: str | None = Field(default=None, max_length=200)
    qualification: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    tender_submission_deadline: datetime | None = None
    opening_tenders_at: datetime | None = None
    delivery_due_at: datetime | None = None


class TenderSearchResponse(BaseModel):
    items: list[TenderOpportunity]
    count: int = Field(ge=0, description="Total hits reported by the official source")
    limit: int
    offset: int


class TenderMatch(BaseModel):
    """A tender ranked against one supplier profile using transparent rules."""

    tender: TenderOpportunity
    match_score: int = Field(ge=0, le=100)
    match_reasons: list[str] = Field(min_length=1, max_length=5)
    deadline_urgency: str = Field(pattern=r"^(unknown|expired|urgent|upcoming|open)$")
    days_to_deadline: int | None = None
    geographic_fit: str = Field(pattern=r"^(matched|different|unknown)$")
    qualification_present: bool
    qualification_fit: Literal["matched", "missing", "unknown", "not_listed"]
    data_completeness: int = Field(ge=0, le=100)
    action_state: Literal[
        "review_now", "monitor", "low_fit", "expired", "excluded", "qualification_gap"
    ]
    next_actions: list[str] = Field(min_length=1, max_length=5)


class CompanyTenderMatchResponse(BaseModel):
    """Tender opportunities ranked for a selected Japanese company."""

    company: Company
    search_query: str = Field(min_length=2, max_length=200)
    expanded_queries: list[str] = Field(min_length=1, max_length=8)
    items: list[TenderMatch]
    count: int = Field(ge=0)
    methodology: str


ProfileTerm = Annotated[str, Field(min_length=2, max_length=100)]
QualificationTerm = Annotated[str, Field(min_length=1, max_length=100)]


class SupplierCapabilityProfile(BaseModel):
    """Customer-supplied bid profile; evaluated per request and never persisted."""

    model_config = ConfigDict(extra="forbid")

    supplier_name: str | None = Field(default=None, min_length=2, max_length=300)
    corporate_number: str | None = Field(default=None, pattern=r"^\d{13}$")
    capabilities: list[ProfileTerm] = Field(min_length=1, max_length=10)
    preferred_prefectures: list[ProfileTerm] = Field(default_factory=list, max_length=10)
    held_qualifications: list[QualificationTerm] = Field(default_factory=list, max_length=20)
    excluded_keywords: list[ProfileTerm] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=10, ge=1, le=50)


class TenderFitAnalysisResponse(BaseModel):
    profile: SupplierCapabilityProfile
    company: Company | None = None
    expanded_queries: list[str] = Field(min_length=1, max_length=24)
    items: list[TenderMatch]
    count: int = Field(ge=0)
    methodology: str


class DemoTenderReadinessItem(BaseModel):
    title_ja: str
    buyer: str | None
    match_score: int = Field(ge=0, le=100)
    deadline_urgency: Literal["unknown", "expired", "urgent", "upcoming", "open"]
    data_completeness: int = Field(ge=0, le=100)
    action_state: Literal[
        "review_now", "monitor", "low_fit", "expired", "excluded", "qualification_gap"
    ]
    next_actions: list[str] = Field(min_length=1, max_length=5)
    source_url: HttpUrl


class DemoTenderReadinessResponse(BaseModel):
    search_query: str
    expanded_queries: list[str] = Field(min_length=1, max_length=4)
    items: list[DemoTenderReadinessItem]
    count: int = Field(ge=0)
    disclaimer: str


class FacetCount(BaseModel):
    value: str
    count: int = Field(ge=1)


class BuyerIntelligenceResponse(BaseModel):
    buyer: str
    search_query: str
    expanded_queries: list[str] = Field(min_length=1, max_length=8)
    opportunities_found: int = Field(ge=0)
    urgent_opportunities: int = Field(ge=0)
    top_categories: list[FacetCount]
    top_prefectures: list[FacetCount]
    latest_published_at: datetime | None = None
    opportunities: list[TenderOpportunity]
    coverage_note: str


TenderChangeAction = Literal["new", "updated", "deadline_changed", "expired"]


class TenderChangeEvent(BaseModel):
    id: int = Field(ge=1)
    tender_id: str
    action: TenderChangeAction
    occurred_at: datetime
    changed_fields: list[str]
    tender: TenderOpportunity
    first_seen_at: datetime
    last_seen_at: datetime


class TenderChangeListResponse(BaseModel):
    items: list[TenderChangeEvent]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)


class TenderMonitoringRefreshResponse(BaseModel):
    queries: list[str]
    tenders_observed: int = Field(ge=0)
    change_events_created: int = Field(ge=0)
    expired_marked: int = Field(ge=0)
    refreshed_at: datetime


class TimelineResponse(BaseModel):
    corporate_number: str
    company_name: str
    items: list[Signal]


class SourceSummary(BaseModel):
    source_name: str
    source_license: str
    record_count: int
    latest_collection: datetime


class SourceListResponse(BaseModel):
    items: list[SourceSummary]


class DemoSignal(BaseModel):
    corporate_number: str
    company_name: str
    prefecture: str | None
    title: str
    occurred_on: date
    score_delta: int
    activity_score: int
    source_url: HttpUrl


class DemoSignalResponse(BaseModel):
    items: list[DemoSignal]
    count: int


class DemoStats(BaseModel):
    companies: int
    procurement_signals: int
    active_companies: int
    official_sources: int


class PublicDataStatus(BaseModel):
    """Non-sensitive freshness and coverage summary for prospective API users."""

    companies: int = Field(ge=0)
    signals: int = Field(ge=0)
    official_sources: int = Field(ge=0)
    latest_collection: datetime | None = None
