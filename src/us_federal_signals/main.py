from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, status

from .adapters.sam import SamError, SamOpportunitiesClient
from .adapters.usaspending import UsaspendingClient, UsaspendingError
from .config import UsSettings
from .matching import rank_federal_opportunities
from .schemas import (
    FederalContractAwardSearchResponse,
    FederalOpportunity,
    FederalOpportunitySearchResponse,
    FederalSupplierFitResponse,
    FederalSupplierProfile,
)
from .security import UsApiAuthenticator


def create_app(
    settings: UsSettings | None = None,
    *,
    sam_client_factory: Callable[..., Any] = SamOpportunitiesClient,
    usaspending_client_factory: Callable[..., Any] = UsaspendingClient,
) -> FastAPI:
    resolved_settings = settings or UsSettings.from_env()
    authenticator = UsApiAuthenticator(resolved_settings)
    app = FastAPI(
        title="US Federal Contract Signals API — Feasibility MVP",
        version="0.1.0",
        description=(
            "Source-linked SAM.gov opportunities and USAspending contract awards with "
            "transparent supplier-fit screening. This build is a feasibility experiment."
        ),
    )
    auth_dependency = authenticator.require_api_key

    def require_sam_key() -> str:
        if not resolved_settings.sam_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SAM.gov opportunity source is not configured",
            )
        return resolved_settings.sam_api_key

    def search_sam(
        *,
        q: str | None,
        posted_from: date,
        posted_to: date,
        notice_types: list[str] | None = None,
        organization_name: str | None = None,
        state_code: str | None = None,
        naics_code: str | None = None,
        psc_code: str | None = None,
        set_aside_code: str | None = None,
        limit: int,
        page: int,
    ) -> FederalOpportunitySearchResponse:
        api_key = require_sam_key()
        try:
            with sam_client_factory(
                api_key=api_key,
                base_url=resolved_settings.sam_base_url,
                timeout_seconds=resolved_settings.source_timeout_seconds,
            ) as client:
                return client.search_opportunities(
                    q=q,
                    posted_from=posted_from,
                    posted_to=posted_to,
                    notice_types=notice_types,
                    organization_name=organization_name,
                    state=state_code,
                    naics_code=naics_code,
                    classification_code=psc_code,
                    set_aside_code=set_aside_code,
                    limit=limit,
                    page=page,
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SamError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="SAM.gov opportunity source is temporarily unavailable",
            ) from exc

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.1.0", "stage": "feasibility"}

    @app.get(
        "/v1/opportunities/search",
        response_model=FederalOpportunitySearchResponse,
        tags=["opportunities"],
        dependencies=[Depends(auth_dependency)],
    )
    def search_opportunities(
        q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
        posted_from: date | None = None,
        posted_to: date | None = None,
        notice_type: Annotated[list[str] | None, Query()] = None,
        organization_name: Annotated[str | None, Query(max_length=300)] = None,
        state_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
        naics_code: Annotated[str | None, Query(pattern=r"^\d{2,6}$")] = None,
        psc_code: Annotated[str | None, Query(max_length=20)] = None,
        set_aside_code: Annotated[str | None, Query(max_length=30)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        page: Annotated[int, Query(ge=0)] = 0,
    ) -> FederalOpportunitySearchResponse:
        end = posted_to or date.today()
        start = posted_from or end - timedelta(days=30)
        return search_sam(
            q=q,
            posted_from=start,
            posted_to=end,
            notice_types=notice_type,
            organization_name=organization_name,
            state_code=state_code,
            naics_code=naics_code,
            psc_code=psc_code,
            set_aside_code=set_aside_code,
            limit=limit,
            page=page,
        )

    @app.get(
        "/v1/awards/search",
        response_model=FederalContractAwardSearchResponse,
        tags=["awards"],
        dependencies=[Depends(auth_dependency)],
    )
    def search_awards(
        q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
        start_date: date | None = None,
        end_date: date | None = None,
        agency: Annotated[str | None, Query(max_length=300)] = None,
        naics_code: Annotated[list[str] | None, Query()] = None,
        psc_code: Annotated[list[str] | None, Query()] = None,
        set_aside_code: Annotated[list[str] | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
    ) -> FederalContractAwardSearchResponse:
        end = end_date or date.today()
        start = start_date or end - timedelta(days=365)
        try:
            with usaspending_client_factory(
                base_url=resolved_settings.usaspending_base_url,
                timeout_seconds=resolved_settings.source_timeout_seconds,
            ) as client:
                return client.search_contract_awards(
                    start_date=start,
                    end_date=end,
                    keywords=[q] if q else None,
                    agency=agency,
                    naics_codes=naics_code,
                    psc_codes=psc_code,
                    set_aside_codes=set_aside_code,
                    limit=limit,
                    page=page,
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except UsaspendingError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="USAspending award source is temporarily unavailable",
            ) from exc

    @app.post(
        "/v1/supplier-fit-analysis",
        response_model=FederalSupplierFitResponse,
        tags=["matching"],
        dependencies=[Depends(auth_dependency)],
    )
    def supplier_fit_analysis(profile: FederalSupplierProfile) -> FederalSupplierFitResponse:
        searched_to = date.today()
        searched_from = searched_to - timedelta(days=profile.lookback_days)
        by_id: dict[str, FederalOpportunity] = {}
        per_query_limit = min(25, max(profile.limit, 5))
        for capability in profile.capabilities:
            response = search_sam(
                q=capability,
                posted_from=searched_from,
                posted_to=searched_to,
                limit=per_query_limit,
                page=0,
            )
            for opportunity in response.items:
                by_id[opportunity.notice_id] = opportunity
        ranked = rank_federal_opportunities(
            profile=profile,
            opportunities=list(by_id.values()),
        )[: profile.limit]
        return FederalSupplierFitResponse(
            profile=profile,
            searched_from=searched_from,
            searched_to=searched_to,
            items=ranked,
            count=len(ranked),
            methodology=(
                "Deterministic screening of source-returned notices using capability terms, "
                "NAICS, PSC, set-aside eligibility, geography, exclusions, and deadline state. "
                "This is not a bid recommendation or eligibility determination."
            ),
        )

    return app


app = create_app()
