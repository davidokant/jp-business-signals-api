from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from .schemas import (
    FederalActionState,
    FederalOpportunity,
    FederalOpportunityMatch,
    FederalSupplierProfile,
)


def rank_federal_opportunities(
    *,
    profile: FederalSupplierProfile,
    opportunities: list[FederalOpportunity],
) -> list[FederalOpportunityMatch]:
    matches = [_match(profile=profile, opportunity=item) for item in opportunities]
    return sorted(matches, key=lambda item: (-item.match_score, item.opportunity.notice_id))


def _match(
    *, profile: FederalSupplierProfile, opportunity: FederalOpportunity
) -> FederalOpportunityMatch:
    searchable = " ".join(
        value
        for value in (
            opportunity.title,
            opportunity.organization_name,
            opportunity.notice_type,
            opportunity.set_aside_description,
        )
        if value
    ).casefold()
    matched_capabilities = sorted(
        {
            term
            for term in profile.capabilities
            if term.strip() and term.casefold() in searchable
        },
        key=str.casefold,
    )
    excluded = sorted(
        {
            term
            for term in profile.excluded_keywords
            if term.strip() and term.casefold() in searchable
        },
        key=str.casefold,
    )

    score = 30
    reasons = ["Returned by SAM.gov for a requested supplier capability"]
    if matched_capabilities:
        score += min(25, 10 + 5 * len(matched_capabilities))
        reasons.append(f"Matched capabilities: {', '.join(matched_capabilities[:3])}")

    naics_fit = _code_fit(opportunity.naics_code, profile.naics_codes)
    if naics_fit == "matched":
        score += 20
        reasons.append("Opportunity NAICS matches the supplier profile")

    psc_fit = _code_fit(opportunity.classification_code, profile.psc_codes)
    if psc_fit == "matched":
        score += 10
        reasons.append("Opportunity PSC matches the supplier profile")

    set_aside_fit: Literal["matched", "gap", "not_listed"] = "not_listed"
    if opportunity.set_aside_code:
        eligible = {value.casefold() for value in profile.eligible_set_asides}
        if opportunity.set_aside_code.casefold() in eligible:
            set_aside_fit = "matched"
            score += 10
            reasons.append("Supplier profile includes the listed set-aside eligibility")
        else:
            set_aside_fit = "gap"
            score -= 25

    geographic_fit: Literal["matched", "different", "unknown"] = "unknown"
    preferred_states = {value.casefold() for value in profile.preferred_states}
    if preferred_states and opportunity.place_of_performance_state:
        if opportunity.place_of_performance_state.casefold() in preferred_states:
            geographic_fit = "matched"
            score += 10
            reasons.append("Place of performance matches a preferred state")
        else:
            geographic_fit = "different"

    deadline_urgency, days_to_deadline = _deadline_state(opportunity)
    if excluded:
        score -= 50
        reasons.append(f"Excluded terms detected: {', '.join(excluded[:2])}")
    score = min(max(score, 0), 100)
    action_state = _action_state(
        score=score,
        deadline_urgency=deadline_urgency,
        set_aside_fit=set_aside_fit,
        excluded=bool(excluded),
    )
    return FederalOpportunityMatch(
        opportunity=opportunity,
        match_score=score,
        match_reasons=reasons[:6],
        action_state=action_state,
        deadline_urgency=deadline_urgency,
        days_to_deadline=days_to_deadline,
        naics_fit=naics_fit,
        psc_fit=psc_fit,
        set_aside_fit=set_aside_fit,
        geographic_fit=geographic_fit,
        next_actions=_next_actions(
            deadline_urgency=deadline_urgency,
            set_aside_fit=set_aside_fit,
            excluded=bool(excluded),
        ),
    )


def _code_fit(
    actual: str | None, requested: list[str]
) -> Literal["matched", "different", "unknown"]:
    if not actual or not requested:
        return "unknown"
    normalized = actual.casefold()
    return (
        "matched"
        if any(
            normalized.startswith(value.strip().casefold())
            or value.strip().casefold().startswith(normalized)
            for value in requested
            if value.strip()
        )
        else "different"
    )


def _deadline_state(
    opportunity: FederalOpportunity,
) -> tuple[Literal["unknown", "expired", "urgent", "upcoming", "open"], int | None]:
    if not opportunity.response_deadline:
        return "unknown", None
    deadline = opportunity.response_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    days = (deadline.astimezone(UTC).date() - datetime.now(UTC).date()).days
    if days < 0:
        return "expired", days
    if days <= 7:
        return "urgent", days
    if days <= 30:
        return "upcoming", days
    return "open", days


def _action_state(
    *, score: int, deadline_urgency: str, set_aside_fit: str, excluded: bool
) -> FederalActionState:
    if deadline_urgency == "expired":
        return "expired"
    if excluded:
        return "excluded"
    if set_aside_fit == "gap":
        return "set_aside_gap"
    if deadline_urgency == "urgent":
        return "deadline_risk"
    if score >= 65:
        return "review_now"
    if score >= 45:
        return "monitor"
    return "low_fit"


def _next_actions(
    *, deadline_urgency: str, set_aside_fit: str, excluded: bool
) -> list[str]:
    actions = ["Review the official SAM.gov notice before bid preparation"]
    if set_aside_fit == "gap":
        actions.append("Confirm set-aside eligibility before investing bid effort")
    elif set_aside_fit == "matched":
        actions.append("Verify that the supplier's set-aside status is current in SAM.gov")
    if deadline_urgency == "urgent":
        actions.append("Confirm the response deadline immediately")
    elif deadline_urgency == "expired":
        actions.append("Archive unless the official notice shows an extension")
    if excluded:
        actions.append("Confirm whether the excluded requirement is disqualifying")
    actions.append("Validate NAICS, PSC, and solicitation instructions at the source")
    return actions[:6]
