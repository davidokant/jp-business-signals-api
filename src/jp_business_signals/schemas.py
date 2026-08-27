from __future__ import annotations

from datetime import date, datetime

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
