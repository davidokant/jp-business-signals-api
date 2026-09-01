from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class UsSettings:
    environment: str
    api_keys: frozenset[str]
    rapidapi_proxy_secret: str | None = None
    rate_limit_per_minute: int = 10
    sam_api_key: str | None = None
    sam_base_url: str = "https://api.sam.gov/opportunities/v2/search"
    usaspending_base_url: str = "https://api.usaspending.gov"
    source_timeout_seconds: float = 30.0
    sam_daily_request_budget: int = 8
    sam_cache_ttl_seconds: float = 900.0
    sam_cache_max_entries: int = 256

    @classmethod
    def from_env(cls) -> UsSettings:
        load_dotenv(override=False)
        environment = os.getenv("US_APP_ENV", "development").strip().lower()
        api_keys = frozenset(
            value.strip()
            for value in os.getenv("US_APP_API_KEYS", "dev-us-key").split(",")
            if value.strip()
        )
        rapidapi_proxy_secret = (
            os.getenv("US_RAPIDAPI_PROXY_SECRET", "").strip() or None
        )
        if environment == "production" and "dev-us-key" in api_keys:
            raise RuntimeError("US_APP_API_KEYS must not contain dev-us-key in production")
        if not api_keys and not rapidapi_proxy_secret:
            raise RuntimeError(
                "Configure US_APP_API_KEYS or US_RAPIDAPI_PROXY_SECRET"
            )
        return cls(
            environment=environment,
            api_keys=api_keys,
            rapidapi_proxy_secret=rapidapi_proxy_secret,
            rate_limit_per_minute=max(
                1, min(600, int(os.getenv("US_RATE_LIMIT_PER_MINUTE", "10")))
            ),
            sam_api_key=os.getenv("SAM_API_KEY", "").strip() or None,
            sam_base_url=os.getenv(
                "SAM_OPPORTUNITIES_BASE_URL",
                "https://api.sam.gov/opportunities/v2/search",
            ).rstrip("/"),
            usaspending_base_url=os.getenv(
                "USASPENDING_BASE_URL", "https://api.usaspending.gov"
            ).rstrip("/"),
            source_timeout_seconds=max(
                1.0, float(os.getenv("US_SOURCE_TIMEOUT_SECONDS", "30"))
            ),
            sam_daily_request_budget=max(
                1,
                min(1000, int(os.getenv("US_SAM_DAILY_REQUEST_BUDGET", "8"))),
            ),
            sam_cache_ttl_seconds=max(
                1.0,
                min(
                    86400.0,
                    float(os.getenv("US_SAM_CACHE_TTL_SECONDS", "900")),
                ),
            ),
            sam_cache_max_entries=max(
                1,
                min(10000, int(os.getenv("US_SAM_CACHE_MAX_ENTRIES", "256"))),
            ),
        )
