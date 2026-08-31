from __future__ import annotations

from datetime import UTC, datetime, timedelta

from us_federal_signals.matching import rank_federal_opportunities
from us_federal_signals.schemas import FederalOpportunity, FederalSupplierProfile


def _opportunity(**overrides: object) -> FederalOpportunity:
    values = {
        "notice_id": "notice-123",
        "title": "Cloud migration and cybersecurity support",
        "organization_name": "General Services Administration",
        "notice_type": "Solicitation",
        "posted_date": datetime.now(UTC).date(),
        "response_deadline": datetime.now(UTC) + timedelta(days=20),
        "naics_code": "541512",
        "classification_code": "DA10",
        "set_aside_code": "SBA",
        "set_aside_description": "Total Small Business Set-Aside",
        "place_of_performance_state": "DC",
        "active": True,
        "source_name": "SAM.gov Contract Opportunities",
        "source_url": "https://sam.gov/opp/notice-123/view",
        "source_license": "Official API terms apply",
        "collected_at": datetime.now(UTC),
    }
    values.update(overrides)
    return FederalOpportunity.model_validate(values)


def test_matching_rewards_codes_eligibility_and_geography() -> None:
    profile = FederalSupplierProfile(
        supplier_name="Example Cloud LLC",
        capabilities=["cloud", "cybersecurity"],
        naics_codes=["5415"],
        psc_codes=["DA10"],
        eligible_set_asides=["SBA"],
        preferred_states=["DC"],
    )
    result = rank_federal_opportunities(profile=profile, opportunities=[_opportunity()])[0]

    assert result.match_score == 100
    assert result.action_state == "review_now"
    assert result.naics_fit == "matched"
    assert result.psc_fit == "matched"
    assert result.set_aside_fit == "matched"
    assert result.geographic_fit == "matched"


def test_matching_surfaces_set_aside_gap_before_high_raw_score() -> None:
    profile = FederalSupplierProfile(capabilities=["cloud"], naics_codes=["541512"])
    result = rank_federal_opportunities(profile=profile, opportunities=[_opportunity()])[0]

    assert result.set_aside_fit == "gap"
    assert result.action_state == "set_aside_gap"
    assert any("set-aside" in action for action in result.next_actions)
