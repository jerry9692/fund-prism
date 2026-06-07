"""Settings tests."""

from pathlib import Path

from fund_research.config.settings import Settings


def test_settings_defaults_cover_phase1_runtime_config() -> None:
    """Settings should provide usable defaults without a local .env file."""
    settings = Settings(_env_file=None)

    assert settings.db_path == "./data/fund_research.duckdb"
    assert settings.cache_dir == "./data/cache"
    assert settings.sample_funds_path == "./data/samples/sample_funds_v0.1.csv"
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert settings.source_timeout_seconds == 20.0
    assert settings.source_retry_count == 2


def test_settings_reads_fund_prefixed_environment(monkeypatch) -> None:
    """Environment variables should use the FUND_ prefix consistently."""
    monkeypatch.setenv("FUND_DB_PATH", "./tmp/test.sqlite")
    monkeypatch.setenv("FUND_SAMPLE_FUNDS_PATH", "./samples/custom.csv")
    monkeypatch.setenv("FUND_SOURCE_TIMEOUT_SECONDS", "8.5")
    monkeypatch.setenv("FUND_SOURCE_RETRY_COUNT", "3")
    monkeypatch.setenv("FUND_TUSHARE_TOKEN", "token-from-env")

    settings = Settings(_env_file=None)

    assert settings.db_path == "./tmp/test.sqlite"
    assert settings.sample_funds_path == "./samples/custom.csv"
    assert settings.source_timeout_seconds == 8.5
    assert settings.source_retry_count == 3
    assert settings.tushare_token == "token-from-env"


def test_env_example_documents_settings_fields() -> None:
    """The checked-in environment template should stay aligned with Settings."""
    env_example = Path(".env.example").read_text(encoding="utf-8")
    expected_keys = [
        "FUND_DB_PATH",
        "FUND_CACHE_DIR",
        "FUND_SAMPLE_FUNDS_PATH",
        "FUND_LOG_LEVEL",
        "FUND_LOG_FILE",
        "FUND_API_HOST",
        "FUND_API_PORT",
        "FUND_API_RELOAD",
        "FUND_TASK_MAX_WORKERS",
        "FUND_TUSHARE_TOKEN",
        "FUND_SOURCE_TIMEOUT_SECONDS",
        "FUND_SOURCE_RETRY_COUNT",
        "FUND_DISCLAIMER",
    ]

    for key in expected_keys:
        assert key in env_example
