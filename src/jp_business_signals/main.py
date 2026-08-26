from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .dataset import load_dataset, sample_dataset_path
from .repository import Repository
from .schemas import (
    Company,
    CompanySearchResponse,
    DemoSignalResponse,
    DemoStats,
    SignalListResponse,
    SourceListResponse,
    TimelineResponse,
)
from .security import ApiAuthenticator, FixedWindowRateLimiter


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    repository = Repository(Path(resolved_settings.database_path))
    authenticator = ApiAuthenticator(resolved_settings)
    demo_limiter = FixedWindowRateLimiter(60)
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

    @app.get(
        "/v1/companies/{corporate_number}",
        response_model=Company,
        tags=["companies"],
        dependencies=[Depends(auth_dependency)],
    )
    def get_company(corporate_number: str) -> Company:
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
        company = repository.get_company(corporate_number)
        if not company:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
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
