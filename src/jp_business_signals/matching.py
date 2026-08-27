from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from .adapters.kkj import PREFECTURE_CODES
from .schemas import Company, SupplierCapabilityProfile, TenderMatch, TenderOpportunity


def rank_company_tenders(
    *,
    company: Company,
    tenders: list[TenderOpportunity],
    query_terms: list[str],
) -> list[TenderMatch]:
    return rank_profile_tenders(
        profile=SupplierCapabilityProfile(
            supplier_name=company.name,
            corporate_number=company.corporate_number,
            capabilities=query_terms,
            preferred_prefectures=[company.prefecture] if company.prefecture else [],
        ),
        tenders=tenders,
        query_terms=query_terms,
        company=company,
    )


def rank_profile_tenders(
    *,
    profile: SupplierCapabilityProfile,
    tenders: list[TenderOpportunity],
    query_terms: list[str],
    company: Company | None = None,
) -> list[TenderMatch]:
    matches = [
        _match_tender(
            tender=tender,
            profile=profile,
            query_terms=query_terms,
            company=company,
        )
        for tender in tenders
    ]
    return sorted(matches, key=lambda item: (-item.match_score, item.tender.tender_id))


def _match_tender(
    *,
    tender: TenderOpportunity,
    profile: SupplierCapabilityProfile,
    query_terms: list[str],
    company: Company | None,
) -> TenderMatch:
    searchable = " ".join(
        value
        for value in (tender.title_ja, tender.category, tender.procedure_type, tender.buyer)
        if value
    ).casefold()
    matched_terms = sorted(
        {term for term in query_terms if term.strip() and term.casefold() in searchable},
        key=str.casefold,
    )
    excluded_terms = sorted(
        {
            term
            for term in profile.excluded_keywords
            if term.strip() and term.casefold() in searchable
        },
        key=str.casefold,
    )

    score = 30
    reasons = ["Returned by the official source for a requested capability"]
    if matched_terms:
        score += min(25, 10 + 5 * len(matched_terms))
        reasons.append(f"Matched capability terms: {', '.join(matched_terms[:3])}")

    geographic_fit: Literal["matched", "different", "unknown"] = "unknown"
    preferred = {_prefecture_key(item) for item in profile.preferred_prefectures}
    if preferred and tender.prefecture:
        if _prefecture_key(tender.prefecture) in preferred:
            geographic_fit = "matched"
            score += 15
            reasons.append("Tender is in a preferred supplier prefecture")
        else:
            geographic_fit = "different"

    tender_qualifications = {item.casefold() for item in tender.qualification}
    held_qualifications = {item.casefold() for item in profile.held_qualifications}
    if not tender_qualifications:
        qualification_fit: Literal["matched", "missing", "unknown", "not_listed"] = (
            "not_listed"
        )
    elif tender_qualifications & held_qualifications:
        qualification_fit = "matched"
        score += 10
        reasons.append("A listed qualification matches the supplier profile")
    elif held_qualifications:
        qualification_fit = "missing"
        score -= 15
    else:
        qualification_fit = "unknown"

    if company:
        if company.procurement_count:
            score += min(company.procurement_count, 10)
            reasons.append("Supplier has recorded public-procurement activity")
        score += min(company.activity_score // 10, 10)

    deadline_urgency, days_to_deadline = _deadline_state(tender)
    completeness_fields = (
        tender.buyer,
        tender.prefecture,
        tender.category,
        tender.published_at,
        tender.tender_submission_deadline,
    )
    completeness = round(sum(value is not None for value in completeness_fields) * 100 / 5)

    if excluded_terms:
        score = max(0, score - 50)
        reasons.append(f"Excluded terms detected: {', '.join(excluded_terms[:2])}")

    score = min(max(score, 0), 100)
    action_state = _action_state(
        score=score,
        deadline_urgency=deadline_urgency,
        qualification_fit=qualification_fit,
        excluded=bool(excluded_terms),
    )
    next_actions = _next_actions(
        deadline_urgency=deadline_urgency,
        qualification_fit=qualification_fit,
        excluded=bool(excluded_terms),
    )
    return TenderMatch(
        tender=tender,
        match_score=score,
        match_reasons=reasons[:5],
        deadline_urgency=deadline_urgency,
        days_to_deadline=days_to_deadline,
        geographic_fit=geographic_fit,
        qualification_present=bool(tender.qualification),
        qualification_fit=qualification_fit,
        data_completeness=completeness,
        action_state=action_state,
        next_actions=next_actions,
    )


def _deadline_state(tender: TenderOpportunity) -> tuple[str, int | None]:
    if not tender.tender_submission_deadline:
        return "unknown", None
    deadline = tender.tender_submission_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    days = (deadline.astimezone(UTC).date() - datetime.now(UTC).date()).days
    urgency = (
        "expired"
        if days < 0
        else "urgent"
        if days <= 7
        else "upcoming"
        if days <= 30
        else "open"
    )
    return urgency, days


def _action_state(
    *,
    score: int,
    deadline_urgency: str,
    qualification_fit: str,
    excluded: bool,
) -> str:
    if deadline_urgency == "expired":
        return "expired"
    if excluded:
        return "excluded"
    if qualification_fit == "missing":
        return "qualification_gap"
    if score >= 65:
        return "review_now"
    if score >= 45:
        return "monitor"
    return "low_fit"


def _next_actions(
    *,
    deadline_urgency: str,
    qualification_fit: str,
    excluded: bool,
) -> list[str]:
    actions = ["Review the official source URL and tender notice"]
    if excluded:
        actions.append("Confirm whether the excluded requirement is a true disqualifier")
    if qualification_fit == "matched":
        actions.append("Confirm that the held qualification is valid for this notice")
    elif qualification_fit == "missing":
        actions.append("Resolve the apparent qualification gap before bid preparation")
    elif qualification_fit in {"unknown", "not_listed"}:
        actions.append("Confirm participation requirements with the buyer")
    if deadline_urgency == "urgent":
        actions.append("Confirm the submission deadline immediately")
    elif deadline_urgency == "expired":
        actions.append("Do not prepare a bid unless the official notice shows an extension")
    return actions[:5]


def _prefecture_key(value: str) -> str:
    normalized = value.strip().casefold()
    return PREFECTURE_CODES.get(normalized, normalized)
