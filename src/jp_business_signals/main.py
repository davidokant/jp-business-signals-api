from __future__ import annotations

from collections import Counter
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from secrets import compare_digest
from threading import Lock
from time import sleep
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .adapters.kkj import KkjClient, KkjError
from .config import Settings
from .dataset import load_dataset, sample_dataset_path
from .matching import rank_company_tenders, rank_profile_tenders
from .query_expansion import expand_capability_query
from .refresh import refresh_gbiz_database
from .repository import Repository
from .schemas import (
    BuyerIntelligenceResponse,
    Company,
    CompanySearchResponse,
    CompanyTenderMatchResponse,
    DemoSignalResponse,
    DemoStats,
    DemoTenderReadinessResponse,
    FacetCount,
    ProcurementSignalListResponse,
    PublicDataStatus,
    SignalListResponse,
    SourceListResponse,
    SupplierCapabilityProfile,
    TenderChangeAction,
    TenderChangeListResponse,
    TenderFitAnalysisResponse,
    TenderMonitoringRefreshResponse,
    TenderOpportunity,
    TenderSearchResponse,
    TimelineResponse,
)
from .security import ApiAuthenticator, FixedWindowRateLimiter
from .tender_history import TenderHistoryStore


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    repository = Repository(Path(resolved_settings.database_path))
    history_path = resolved_settings.tender_history_database_path or Path(
        resolved_settings.database_path
    ).with_name("tender-history.db")
    tender_history = TenderHistoryStore(history_path)
    authenticator = ApiAuthenticator(resolved_settings)
    demo_limiter = FixedWindowRateLimiter(60)
    tender_demo_limiter = FixedWindowRateLimiter(10)
    refresh_lock = Lock()
    tender_history_lock = Lock()
    static_directory = Path(__file__).with_name("static")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        repository.initialize()
        tender_history.initialize()
        if resolved_settings.auto_seed_sample and repository.count_companies() == 0:
            dataset = load_dataset(sample_dataset_path())
            repository.upsert_companies(dataset.companies)
            repository.insert_signals(dataset.signals)
        yield

    app = FastAPI(
        title="JP Business Signals API",
        version="0.2.0",
        description=(
            "Source-traceable Japanese company, procurement, tender-readiness, and "
            "tender-change intelligence built from official public sources."
        ),
        lifespan=lifespan,
        openapi_tags=[
            {"name": "companies", "description": "Company search and profiles"},
            {"name": "signals", "description": "Time-ordered public activity signals"},
            {"name": "procurement", "description": "Supplier-screening procurement event feed"},
            {
                "name": "tenders",
                "description": "Official Japanese public tender opportunity search",
            },
            {
                "name": "matching",
                "description": "Transparent supplier-to-tender opportunity matching",
            },
            {
                "name": "intelligence",
                "description": "Buyer demand summaries and machine-readable tender changes",
            },
            {"name": "sources", "description": "Data provenance and license summaries"},
        ],
    )
    app.state.repository = repository
    app.state.tender_history = tender_history
    app.state.settings = resolved_settings
    app.mount("/assets", StaticFiles(directory=static_directory), name="assets")

    auth_dependency = authenticator.require_api_key

    async def require_demo_rate_limit(request: Request) -> None:
        client_host = request.client.host if request.client else "unknown"
        if not demo_limiter.allow(f"demo:{client_host}"):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demo rate limit exceeded",
                headers={"Retry-After": "60"},
            )

    async def require_tender_demo_rate_limit(request: Request) -> None:
        client_host = request.client.host if request.client else "unknown"
        if not tender_demo_limiter.allow(f"tender-demo:{client_host}"):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Tender demo rate limit exceeded",
                headers={"Retry-After": "60"},
            )

    def require_tender_source() -> None:
        if not resolved_settings.kkj_api_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Tender opportunity source is not enabled yet",
            )

    def require_refresh_token(request: Request) -> None:
        supplied_token = request.headers.get("X-Refresh-Token", "")
        configured_token = resolved_settings.refresh_token
        if not configured_token or not compare_digest(supplied_token, configured_token):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    def collect_official_tenders(
        queries: tuple[str, ...],
        *,
        buyer: str | None = None,
        limit_per_query: int = 25,
    ) -> tuple[list[TenderOpportunity], int]:
        require_tender_source()
        by_id: dict[str, TenderOpportunity] = {}
        try:
            with KkjClient(
                base_url=resolved_settings.kkj_base_url,
                timeout_seconds=resolved_settings.kkj_timeout_seconds,
            ) as client:
                for index, query in enumerate(queries):
                    if index:
                        sleep(resolved_settings.kkj_request_interval_seconds)
                    response = client.search_tenders(
                        q=query,
                        buyer=buyer,
                        limit=limit_per_query,
                    )
                    for tender in response.items:
                        by_id[tender.tender_id] = tender
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        except KkjError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Official tender source is temporarily unavailable",
            ) from exc

        with tender_history_lock:
            results = tender_history.upsert_many(
                by_id.values(), observed_at=datetime.now(UTC)
            )
        events_created = sum(len(result.actions) for result in results)
        return list(by_id.values()), events_created

    def expanded_capabilities(
        capabilities: list[str] | tuple[str, ...],
        *,
        max_queries: int,
    ) -> tuple[str, ...]:
        expanded: list[str] = []
        seen: set[str] = set()
        for capability in capabilities:
            for query in expand_capability_query(capability, max_queries=4):
                key = query.casefold()
                if key in seen:
                    continue
                seen.add(key)
                expanded.append(query)
                if len(expanded) >= max_queries:
                    return tuple(expanded)
        return tuple(expanded)

    @app.get("/", response_class=FileResponse, include_in_schema=False)
    def landing_page() -> FileResponse:
        return FileResponse(static_directory / "index.html")

    @app.get("/privacy", response_class=FileResponse, include_in_schema=False)
    def privacy_page() -> FileResponse:
        return FileResponse(static_directory / "privacy.html")

    @app.get("/terms", response_class=FileResponse, include_in_schema=False)
    def terms_page() -> FileResponse:
        return FileResponse(static_directory / "terms.html")

    @app.get("/data-sources", response_class=FileResponse, include_in_schema=False)
    def data_sources_page() -> FileResponse:
        return FileResponse(static_directory / "data-sources.html")

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.2.0"}

    @app.get(
        "/status",
        response_model=PublicDataStatus,
        tags=["operations"],
    )
    def public_data_status() -> PublicDataStatus:
        """Public coverage and freshness summary; no API key required."""
        return repository.public_data_status()

    @app.post("/internal/refresh-gbiz", include_in_schema=False)
    def refresh_gbiz(request: Request) -> PublicDataStatus:
        """Run the daily official-data refresh; callable only by the scheduled workflow."""
        require_refresh_token(request)
        if not refresh_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Refresh already running"
            )
        try:
            refresh_gbiz_database(resolved_settings)
            return repository.public_data_status()
        finally:
            refresh_lock.release()

    @app.post("/internal/refresh-tenders", include_in_schema=False)
    def refresh_tenders(request: Request) -> TenderMonitoringRefreshResponse:
        """Observe configured tender topics and persist explicit change events."""
        require_refresh_token(request)
        if not refresh_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Refresh already running"
            )
        try:
            queries = resolved_settings.tender_watch_queries
            tenders, event_count = collect_official_tenders(queries, limit_per_query=100)
            refreshed_at = datetime.now(UTC)
            with tender_history_lock:
                expired = tender_history.mark_expired(as_of=refreshed_at)
            return TenderMonitoringRefreshResponse(
                queries=list(queries),
                tenders_observed=len(tenders),
                change_events_created=event_count,
                expired_marked=len(expired),
                refreshed_at=refreshed_at,
            )
        finally:
            refresh_lock.release()

    @app.get(
        "/demo/stats",
        response_model=DemoStats,
        tags=["demo"],
        dependencies=[Depends(require_demo_rate_limit)],
    )
    def demo_stats() -> DemoStats:
        return repository.demo_stats()

    @app.get(
        "/demo/signals",
        response_model=DemoSignalResponse,
        tags=["demo"],
        dependencies=[Depends(require_demo_rate_limit)],
    )
    def demo_signals(
        q: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
        limit: Annotated[int, Query(ge=1, le=12)] = 6,
    ) -> DemoSignalResponse:
        items = repository.search_demo_procurement(q=q, limit=limit)
        return DemoSignalResponse(items=items, count=len(items))

    @app.get(
        "/demo/tender-readiness",
        response_model=DemoTenderReadinessResponse,
        tags=["demo"],
        dependencies=[Depends(require_tender_demo_rate_limit)],
    )
    def demo_tender_readiness(
        q: Annotated[str, Query(min_length=2, max_length=100)] = "cloud services",
    ) -> DemoTenderReadinessResponse:
        """Show three source-linked readiness results without an API key."""
        queries = expanded_capabilities([q], max_queries=3)
        tenders, _ = collect_official_tenders(queries, limit_per_query=5)
        profile = SupplierCapabilityProfile(
            supplier_name="Demo supplier",
            capabilities=[q],
            limit=3,
        )
        ranked = rank_profile_tenders(
            profile=profile,
            tenders=tenders,
            query_terms=list(queries),
        )
        open_items = [item for item in ranked if item.action_state != "expired"]
        selected = (open_items or ranked)[:3]
        return DemoTenderReadinessResponse(
            search_query=q,
            expanded_queries=list(queries),
            items=[
                {
                    "title_ja": item.tender.title_ja,
                    "buyer": item.tender.buyer,
                    "match_score": item.match_score,
                    "deadline_urgency": item.deadline_urgency,
                    "data_completeness": item.data_completeness,
                    "action_state": item.action_state,
                    "next_actions": item.next_actions,
                    "source_url": item.tender.source_url,
                }
                for item in selected
            ],
            count=len(selected),
            disclaimer=(
                "Illustrative rule-based readiness only. Verify eligibility, attachments, "
                "deadlines, and all requirements on the linked official notice."
            ),
        )

    @app.get(
        "/v1/companies/search",
        response_model=CompanySearchResponse,
        tags=["companies"],
        dependencies=[Depends(auth_dependency)],
    )
    def search_companies(
        q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
        prefecture: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
        industry: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
        min_activity_score: Annotated[int, Query(ge=0, le=100)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> CompanySearchResponse:
        items = repository.search_companies(
            q=q,
            prefecture=prefecture,
            industry=industry,
            min_activity_score=min_activity_score,
            limit=limit,
            offset=offset,
        )
        return CompanySearchResponse(items=items, count=len(items), limit=limit, offset=offset)

    def company_by_number(corporate_number: str) -> Company:
        if len(corporate_number) != 13 or not corporate_number.isdigit():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="corporate_number must contain exactly 13 digits",
            )
        company = repository.get_company(corporate_number)
        if not company:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
        return company

    @app.get(
        "/v1/companies/{corporate_number}",
        response_model=Company,
        tags=["companies"],
        dependencies=[Depends(auth_dependency)],
    )
    def get_company(corporate_number: str) -> Company:
        return company_by_number(corporate_number)

    @app.get(
        "/v1/company-details",
        response_model=Company,
        tags=["companies"],
        dependencies=[Depends(auth_dependency)],
    )
    def get_company_details(
        corporate_number: Annotated[str, Query(pattern=r"^\d{13}$")],
    ) -> Company:
        """RapidAPI-friendly company lookup using an explicit query parameter."""
        return company_by_number(corporate_number)

    def timeline_for_company(
        corporate_number: str,
        limit: int,
        offset: int,
    ) -> TimelineResponse:
        company = company_by_number(corporate_number)
        items = repository.list_signals(
            since=None,
            signal_type=None,
            corporate_number=corporate_number,
            limit=limit,
            offset=offset,
        )
        return TimelineResponse(
            corporate_number=corporate_number,
            company_name=company.name,
            items=items,
        )

    @app.get(
        "/v1/companies/{corporate_number}/timeline",
        response_model=TimelineResponse,
        tags=["companies"],
        dependencies=[Depends(auth_dependency)],
    )
    def company_timeline(
        corporate_number: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> TimelineResponse:
        return timeline_for_company(
            corporate_number=corporate_number,
            limit=limit,
            offset=offset,
        )

    @app.get(
        "/v1/company-timeline",
        response_model=TimelineResponse,
        tags=["companies"],
        dependencies=[Depends(auth_dependency)],
    )
    def get_company_signal_timeline(
        corporate_number: Annotated[str, Query(pattern=r"^\d{13}$")],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> TimelineResponse:
        """RapidAPI-friendly timeline lookup using an explicit query parameter."""
        return timeline_for_company(
            corporate_number=corporate_number,
            limit=limit,
            offset=offset,
        )

    @app.get(
        "/v1/procurement-signals",
        response_model=ProcurementSignalListResponse,
        tags=["procurement"],
        dependencies=[Depends(auth_dependency)],
    )
    def search_procurement_signals(
        since: date | None = None,
        q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
        prefecture: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> ProcurementSignalListResponse:
        """Search source-traceable procurement events with supplier context."""
        items = repository.search_procurement_signals(
            since=since,
            q=q,
            prefecture=prefecture,
            limit=limit,
            offset=offset,
        )
        return ProcurementSignalListResponse(
            items=items, count=len(items), limit=limit, offset=offset
        )

    @app.get(
        "/v1/tenders/search",
        response_model=TenderSearchResponse,
        tags=["tenders"],
        dependencies=[Depends(auth_dependency)],
    )
    def search_tenders(
        q: Annotated[str, Query(min_length=2, max_length=200)],
        buyer: Annotated[str | None, Query(min_length=2, max_length=300)] = None,
        prefecture: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
        category: Annotated[str | None, Query(min_length=2, max_length=20)] = None,
        published_from: date | None = None,
        published_to: date | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0, le=900)] = 0,
    ) -> TenderSearchResponse:
        """Search source-linked public tenders; source free text and attachments are excluded."""
        if not resolved_settings.kkj_api_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Tender opportunity source is not enabled yet",
            )
        try:
            with KkjClient(
                base_url=resolved_settings.kkj_base_url,
                timeout_seconds=resolved_settings.kkj_timeout_seconds,
            ) as client:
                response = client.search_tenders(
                    q=q,
                    buyer=buyer,
                    prefecture=prefecture,
                    category=category,
                    published_from=published_from,
                    published_to=published_to,
                    limit=limit,
                    offset=offset,
                )
                with tender_history_lock:
                    tender_history.upsert_many(
                        response.items, observed_at=datetime.now(UTC)
                    )
                return response
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        except KkjError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Official tender source is temporarily unavailable",
            ) from exc

    @app.get(
        "/v1/company-tender-matches",
        response_model=CompanyTenderMatchResponse,
        tags=["matching"],
        dependencies=[Depends(auth_dependency)],
    )
    def company_tender_matches(
        corporate_number: Annotated[str, Query(pattern=r"^\d{13}$")],
        q: Annotated[str, Query(min_length=2, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> CompanyTenderMatchResponse:
        """Rank official tender results for a company using explicit, inspectable signals."""
        company = company_by_number(corporate_number)
        queries = expanded_capabilities([q], max_queries=4)
        tenders, _ = collect_official_tenders(
            queries,
            limit_per_query=min(max(limit, 10), 25),
        )
        matches = rank_company_tenders(
            company=company,
            tenders=tenders,
            query_terms=list(queries),
        )[:limit]
        return CompanyTenderMatchResponse(
            company=company,
            search_query=q,
            expanded_queries=list(queries),
            items=matches,
            count=len(matches),
            methodology=(
                "Deterministic English-to-Japanese capability expansion and transparent "
                "rule-based ranking using keyword evidence, prefecture alignment, public "
                "procurement activity, supplier activity score, qualification visibility, "
                "deadline urgency, and explicit exclusions. It is decision support, not an "
                "eligibility or award prediction."
            ),
        )

    @app.post(
        "/v1/tender-fit-analysis",
        response_model=TenderFitAnalysisResponse,
        tags=["matching"],
        dependencies=[Depends(auth_dependency)],
    )
    def tender_fit_analysis(
        profile: SupplierCapabilityProfile,
    ) -> TenderFitAnalysisResponse:
        """Evaluate a request-scoped supplier profile without storing customer inputs."""
        company = None
        effective_profile = profile
        if profile.corporate_number:
            company = company_by_number(profile.corporate_number)
            prefectures = list(profile.preferred_prefectures)
            if company.prefecture and company.prefecture.casefold() not in {
                item.casefold() for item in prefectures
            }:
                prefectures.insert(0, company.prefecture)
            effective_profile = profile.model_copy(
                update={
                    "supplier_name": profile.supplier_name or company.name,
                    "preferred_prefectures": prefectures[:10],
                }
            )

        queries = expanded_capabilities(profile.capabilities, max_queries=6)
        tenders, _ = collect_official_tenders(
            queries,
            limit_per_query=min(max(profile.limit, 10), 25),
        )
        matches = rank_profile_tenders(
            profile=effective_profile,
            tenders=tenders,
            query_terms=list(queries),
            company=company,
        )[: profile.limit]
        return TenderFitAnalysisResponse(
            profile=effective_profile,
            company=company,
            expanded_queries=list(queries),
            items=matches,
            count=len(matches),
            methodology=(
                "Request-scoped capability profile with deterministic English-to-Japanese "
                "query expansion, official-result deduplication, qualification comparison, "
                "location preference, exclusions, deadline readiness, and machine-readable "
                "action states. The profile is not persisted."
            ),
        )

    @app.get(
        "/v1/buyer-intelligence",
        response_model=BuyerIntelligenceResponse,
        tags=["intelligence"],
        dependencies=[Depends(auth_dependency)],
    )
    def buyer_intelligence(
        buyer: Annotated[str, Query(min_length=2, max_length=300)],
        q: Annotated[str, Query(min_length=2, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=50)] = 25,
    ) -> BuyerIntelligenceResponse:
        """Summarize a public buyer's current demand for one supplier capability."""
        queries = expanded_capabilities([q], max_queries=4)
        tenders, _ = collect_official_tenders(
            queries,
            buyer=buyer,
            limit_per_query=min(max(limit, 10), 25),
        )

        def publication_key(tender: TenderOpportunity) -> float:
            published = tender.published_at
            if not published:
                return 0.0
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
            return published.timestamp()

        selected = sorted(tenders, key=publication_key, reverse=True)[:limit]
        readiness = rank_profile_tenders(
            profile=SupplierCapabilityProfile(
                supplier_name="Buyer demand analysis",
                capabilities=[q],
            ),
            tenders=selected,
            query_terms=list(queries),
        )
        categories = Counter(item.category for item in selected if item.category)
        prefectures = Counter(item.prefecture for item in selected if item.prefecture)
        published_dates = [
            item.published_at.replace(tzinfo=UTC)
            if item.published_at and item.published_at.tzinfo is None
            else item.published_at
            for item in selected
            if item.published_at
        ]
        return BuyerIntelligenceResponse(
            buyer=buyer,
            search_query=q,
            expanded_queries=list(queries),
            opportunities_found=len(selected),
            urgent_opportunities=sum(
                item.deadline_urgency == "urgent" for item in readiness
            ),
            top_categories=[
                FacetCount(value=value, count=count)
                for value, count in categories.most_common(5)
            ],
            top_prefectures=[
                FacetCount(value=value, count=count)
                for value, count in prefectures.most_common(5)
            ],
            latest_published_at=max(published_dates) if published_dates else None,
            opportunities=selected,
            coverage_note=(
                "Aggregates current safe metadata returned by the official tender search. "
                "It is not historical spend, award, incumbent-supplier, or budget data."
            ),
        )

    @app.get(
        "/v1/tender-changes",
        response_model=TenderChangeListResponse,
        tags=["intelligence"],
        dependencies=[Depends(auth_dependency)],
    )
    def tender_changes(
        since: datetime | None = None,
        action: TenderChangeAction | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> TenderChangeListResponse:
        """List observed new, updated, deadline-changed, and expired tenders."""
        try:
            changes = tender_history.list_changes(
                since=since,
                action=action,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        return TenderChangeListResponse(
            items=[
                {
                    "id": change.id,
                    "tender_id": change.tender_id,
                    "action": change.action,
                    "occurred_at": change.occurred_at,
                    "changed_fields": list(change.changed_fields),
                    "tender": change.tender,
                    "first_seen_at": change.first_seen_at,
                    "last_seen_at": change.last_seen_at,
                }
                for change in changes
            ],
            count=len(changes),
            limit=limit,
            offset=offset,
        )

    @app.get(
        "/v1/signals",
        response_model=SignalListResponse,
        tags=["signals"],
        dependencies=[Depends(auth_dependency)],
    )
    def list_signals(
        since: date | None = None,
        signal_type: Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]{1,49}$")] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> SignalListResponse:
        items = repository.list_signals(
            since=since,
            signal_type=signal_type,
            corporate_number=None,
            limit=limit,
            offset=offset,
        )
        return SignalListResponse(items=items, count=len(items), limit=limit, offset=offset)

    @app.get(
        "/v1/sources",
        response_model=SourceListResponse,
        tags=["sources"],
        dependencies=[Depends(auth_dependency)],
    )
    def list_sources() -> SourceListResponse:
        return SourceListResponse(items=repository.list_sources())

    return app


app = create_app()
