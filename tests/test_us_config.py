from __future__ import annotations

import pytest

from us_federal_signals.config import UsSettings


def test_us_production_config_accepts_rapidapi_only_and_clamps_guardrails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("US_APP_ENV", "production")
    monkeypatch.setenv("US_APP_API_KEYS", "")
    monkeypatch.setenv("US_RAPIDAPI_PROXY_SECRET", "proxy-secret")
    monkeypatch.setenv("US_RATE_LIMIT_PER_MINUTE", "9999")
    monkeypatch.setenv("US_SAM_DAILY_REQUEST_BUDGET", "9999")
    monkeypatch.setenv("US_SAM_CACHE_TTL_SECONDS", "999999")
    monkeypatch.setenv("US_SAM_CACHE_MAX_ENTRIES", "99999")

    settings = UsSettings.from_env()

    assert settings.api_keys == frozenset()
    assert settings.rapidapi_proxy_secret == "proxy-secret"
    assert settings.rate_limit_per_minute == 600
    assert settings.sam_daily_request_budget == 1000
    assert settings.sam_cache_ttl_seconds == 86400
    assert settings.sam_cache_max_entries == 10000


def test_us_production_config_rejects_development_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("US_APP_ENV", "production")
    monkeypatch.setenv("US_APP_API_KEYS", "dev-us-key")
    monkeypatch.delenv("US_RAPIDAPI_PROXY_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="dev-us-key"):
        UsSettings.from_env()
