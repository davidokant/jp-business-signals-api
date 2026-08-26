from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    database_path: Path
    api_keys: frozenset[str]
    rapidapi_proxy_secret: str | None
    rate_limit_per_minute: int
    auto_seed_sample: bool
    gbiz_api_token: str | None = None
    gbiz_base_url: str = "https://api.info.gbiz.go.jp/hojin"
    gbiz_timeout_seconds: float = 30.0
    gbiz_request_interval_seconds: float = 0.25
    refresh_token: str | None = None

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> Settings:
        dotenv_path = env_file or Path.cwd() / ".env"
        load_dotenv(dotenv_path=dotenv_path, override=False)
        environment = os.getenv("APP_ENV", "development").strip().lower()
        api_keys = frozenset(
            key.strip()
            for key in os.getenv("APP_API_KEYS", "dev-local-key").split(",")
            if key.strip()
        )
        rapidapi_secret = os.getenv("APP_RAPIDAPI_PROXY_SECRET", "").strip() or None
        auto_seed = _as_bool(os.getenv("APP_AUTO_SEED_SAMPLE"), environment != "production")

        if environment == "production" and "dev-local-key" in api_keys:
            raise RuntimeError("APP_API_KEYS must not contain dev-local-key in production")
        if not api_keys and not rapidapi_secret:
            raise RuntimeError("Configure APP_API_KEYS or APP_RAPIDAPI_PROXY_SECRET")

        return cls(
            environment=environment,
            database_path=Path(os.getenv("APP_DATABASE_PATH", "./data/app.db")),
            api_keys=api_keys,
            rapidapi_proxy_secret=rapidapi_secret,
            rate_limit_per_minute=max(1, int(os.getenv("APP_RATE_LIMIT_PER_MINUTE", "120"))),
            auto_seed_sample=auto_seed,
            gbiz_api_token=os.getenv("GBIZ_API_TOKEN", "").strip() or None,
            gbiz_base_url=os.getenv("GBIZ_BASE_URL", "https://api.info.gbiz.go.jp/hojin").rstrip(
                "/"
            ),
            gbiz_timeout_seconds=max(1.0, float(os.getenv("GBIZ_TIMEOUT_SECONDS", "30"))),
            gbiz_request_interval_seconds=max(
                0.0, float(os.getenv("GBIZ_REQUEST_INTERVAL_SECONDS", "0.25"))
            ),
            refresh_token=os.getenv("APP_REFRESH_TOKEN", "").strip() or None,
        )
