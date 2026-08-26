from __future__ import annotations

from jp_business_signals.config import Settings


def test_settings_load_gbiz_token_from_explicit_env_file(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_API_KEYS=test-key\nAPP_DATABASE_PATH=./test.db\nGBIZ_API_TOKEN=token-from-dotenv\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GBIZ_API_TOKEN", raising=False)
    monkeypatch.delenv("APP_API_KEYS", raising=False)
    monkeypatch.delenv("APP_DATABASE_PATH", raising=False)

    settings = Settings.from_env(env_file=env_file)

    assert settings.gbiz_api_token == "token-from-dotenv"
    assert settings.api_keys == frozenset({"test-key"})
