from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class FederalSourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=1, max_length=200)
    source_url: HttpUrl
    source_license: str = Field(min_length=1, max_length=500)
    collected_at: datetime


class FederalOpportunity(FederalSourceRecord):
    """Safe, source-linked metadata for one SAM.gov contract opportunity."""

    notice_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=1000)
    solicitation_number: str | None = Field(default=None, max_length=200)
    organization_name: str | None = Field(default=None, max_length=1000)
    notice_type: str | None = Field(default=None, max_length=200)
    base_type: str | None = Field(default=None, max_length=200)
    posted_date: date | None = None
    response_deadline: datetime | None = None
    naics_code: str | None = Field(default=None, pattern=r"^\d{2,6}$")
    classification_code: str | None = Field(default=None, max_length=20)
    set_aside_code: str | None = Field(default=None, max_length=30)
    set_aside_description: str | None = Field(default=None, max_length=500)
    place_of_performance_state: str | None = Field(default=None, max_length=100)
    place_of_performance_city: str | None = Field(default=None, max_length=200)
    active: bool | None = None


class FederalOpportunitySearchResponse(BaseModel):
    items: list[FederalOpportunity]
    count: int = Field(ge=0, description="Total records reported by SAM.gov")
    limit: int = Field(ge=1, le=1000)
    page: int = Field(ge=0)


class FederalContractAward(FederalSourceRecord):
    """Normalized contract-award metadata returned by USAspending."""

    award_id: str = Field(min_length=1, max_length=300)
    recipient_name: str | None = Field(default=None, max_length=500)
    recipient_uei: str | None = Field(default=None, max_length=30)
    start_date: date | None = None
    end_date: date | None = None
    award_amount: Decimal | None = None
    awarding_agency: str | None = Field(default=None, max_length=500)
    awarding_sub_agency: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    naics_code: str | None = Field(default=None, max_length=20)
    naics_description: str | None = Field(default=None, max_length=500)
    psc_code: str | None = Field(default=None, max_length=20)
    psc_description: str | None = Field(default=None, max_length=500)


class FederalContractAwardSearchResponse(BaseModel):
    items: list[FederalContractAward]
    count: int = Field(ge=0)
    page: int = Field(ge=1)
    limit: int = Field(ge=1, le=100)
    has_next: bool


CapabilityTerm = Annotated[str, Field(min_length=2, max_length=100)]
CodeTerm = Annotated[str, Field(min_length=1, max_length=30)]


class FederalSupplierProfile(BaseModel):
    """Ephemeral supplier profile used for transparent opportunity matching."""

    model_config = ConfigDict(extra="forbid")

    supplier_name: str | None = Field(default=None, min_length=2, max_length=300)
    uei: str | None = Field(default=None, min_length=12, max_length=12)
    capabilities: list[CapabilityTerm] = Field(min_length=1, max_length=5)
    naics_codes: list[CodeTerm] = Field(default_factory=list, max_length=20)
    psc_codes: list[CodeTerm] = Field(default_factory=list, max_length=20)
    eligible_set_asides: list[CodeTerm] = Field(default_factory=list, max_length=20)
    preferred_states: list[CodeTerm] = Field(default_factory=list, max_length=20)
    excluded_keywords: list[CapabilityTerm] = Field(default_factory=list, max_length=20)
    lookback_days: int = Field(default=30, ge=1, le=365)
    limit: int = Field(default=10, ge=1, le=50)


FederalActionState = Literal[
    "review_now",
    "monitor",
    "set_aside_gap",
    "deadline_risk",
    "low_fit",
    "expired",
    "excluded",
]


class FederalOpportunityMatch(BaseModel):
    opportunity: FederalOpportunity
    match_score: int = Field(ge=0, le=100)
    match_reasons: list[str] = Field(min_length=1, max_length=6)
    action_state: FederalActionState
    deadline_urgency: Literal["unknown", "expired", "urgent", "upcoming", "open"]
    days_to_deadline: int | None = None
    naics_fit: Literal["matched", "different", "unknown"]
    psc_fit: Literal["matched", "different", "unknown"]
    set_aside_fit: Literal["matched", "gap", "not_listed"]
    geographic_fit: Literal["matched", "different", "unknown"]
    next_actions: list[str] = Field(min_length=1, max_length=6)


class FederalSupplierFitResponse(BaseModel):
    profile: FederalSupplierProfile
    searched_from: date
    searched_to: date
    items: list[FederalOpportunityMatch]
    count: int = Field(ge=0)
    methodology: str
