from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from jp_business_signals.config import Settings
from jp_business_signals.main import create_app


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        environment="test",
        database_path=tmp_path / "test.db",
        api_keys=frozenset({"test-key"}),
        rapidapi_proxy_secret="rapid-secret",
        rate_limit_per_minute=100,
        auto_seed_sample=True,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-key"}
