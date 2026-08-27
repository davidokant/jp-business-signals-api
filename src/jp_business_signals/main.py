from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from secrets import compare_digest
from threading import Lock
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .adapters.kkj import KkjClient, KkjError
from .config import Settings
from .dataset import load_dataset, sample_dataset_path
from .refresh import refresh_gbiz_database
from .repository import Repository
from .schemas import (
    Company,
    CompanySearchResponse,
    CompanyTenderMatchResponse,
    DemoSignalResponse,
    DemoStats,
    ProcurementSignalListResponse,
    PublicDataStatus,
    SignalListResponse,
    SourceListResponse,
    TenderSearchResponse,
    TimelineResponse,
)
from .security import ApiAuthenticator, FixedWindowRateLimiter


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    repository = Repository(Path(resolved_settings.database_path))
    authenticator = ApiAuthenticator(resolved_settings)
    demo_limiter = FixedWindowRateLimiter(60)
    refresh_lock = Lock()
    static_directory = Path(__file__).with_name("static")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        repository.initialize()
        if resolved_settings.auto_seed_sample and repository.count_companies() == 0:
            dataset = load_dataset(sample_dataset_path())
            repository.upsert_companies(dataset.companies)
            repository.insert_signals(dataset.signals)
        yield

    app = FastAPI(
        title="JP Business Signals API",
        version="0.1.0",
        description=(
            "Source-traceable company profiles and public business activity signals. "
            "The bundled dataset is synthetic and intended only for MVP testing."
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
            {"name": "sources", "description": "Data provenance and license summaries"},
        ],
    )
    app.state.repository = repository
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
        return {"status": "ok", "version": "0.1.0"}

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
        supplied_token = request.headers.get("X-Refresh-Token", "")
        configured_token = resolved_settings.refresh_token
        if not configured_token or not compare_digest(supplied_token, configured_token):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        if not refresh_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Refresh already running"
            )
        try:
            refresh_gbiz_database(resolved_settings)
            return repository.public_data_status()
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
                return client.search_tenders(
                    q=q,
                    buyer=buyer,
                    prefecture=prefecture,
                    category=category,
                    published_from=published_from,
                    published_to=published_to,
                    limit=limit,
                    offset=offset,
                )
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
                results = client.search_tenders(q=q, limit=limit)
        except KkjError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Official tender source is temporarily unavailable",
            ) from exc

        normalized_query = q.casefold()
        matches = []
        for tender in results.items:
            score = 35
            reasons = ["Matches the requested capability keyword"]
            if company.prefecture and tender.prefecture:
                if company.prefecture.casefold() == tender.prefecture.casefold():
                    score += 25
                    reasons.append("Tender is in the supplier's registered prefecture")
            if normalized_query in tender.title_ja.casefold():
                score += 15
                reasons.append("Keyword appears in the tender title")
            if company.procurement_count:
                score += min(company.procurement_count, 10)
                reasons.append("Supplier has recorded public-procurement activity")
            score += min(company.activity_score // 10, 10)
            matches.append((score, tender.tender_id, tender, reasons[:5]))
        matches.sort(key=lambda item: (-item[0], item[1]))
        return CompanyTenderMatchResponse(
            company=company,
            search_query=q,
            items=[
                {
                    "tender": tender,
                    "match_score": min(score, 100),
                    "match_reasons": reasons,
                }
                for score, _, tender, reasons in matches
            ],
            count=len(matches),
            methodology=(
                "Transparent rule-based ranking: requested capability keyword, "
                "supplier/tender prefecture alignment, title keyword occurrence, "
                "recorded procurement activity, and supplier activity score. "
                "Scores are relevance indicators, not eligibility or award predictions."
            ),
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
