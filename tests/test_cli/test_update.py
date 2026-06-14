"""CLI update tests."""

from pathlib import Path

from typer.testing import CliRunner

from fund_research.cli.main import _selected_update_entities, app


def _write_sample(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                (
                    "fund_code,short_name,company,expected_style,expected_turnover,"
                    "added_reason,confirmed_turnover,confirmed_turnover_source,"
                    "num_reports_available"
                ),
                "000001,华夏成长混合,华夏基金,均衡,低,测试,pending,pending,8",
            ]
        ),
        encoding="utf-8",
    )


def test_update_accepts_domains_alias_for_sample_funds(tmp_path: Path) -> None:
    """The update command should support --domains aliases from Phase 1 requirements."""
    sample_path = tmp_path / "sample.csv"
    db_path = tmp_path / "fund_research.sqlite"
    _write_sample(sample_path)

    result = CliRunner().invoke(
        app,
        [
            "update",
            "--domains",
            "sample",
            "--sample",
            str(sample_path),
            "--db-path",
            str(db_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "sample_funds" in result.output
    assert "DRY-RUN" in result.output


def test_update_rejects_unknown_domain() -> None:
    """Unknown --domains values should fail before running data updates."""
    result = CliRunner().invoke(app, ["update", "--domains", "not-a-domain"])

    assert result.exit_code == 1
    assert "暂不支持的数据类型" in result.output
    assert "not-a-domain" in result.output


def test_update_domains_include_benchmark_industry_sources() -> None:
    """New benchmark industry data domains should resolve in update order."""
    selected = _selected_update_entities(
        "sample-funds",
        "benchmark-members,stock-industry,benchmark-industry",
    )

    assert selected == ["benchmark-members", "stock-industry", "benchmark-industry"]


def test_update_help_includes_stock_industry_stability_options() -> None:
    """stock-industry should expose controls for segmented, throttled updates."""
    result = CliRunner().invoke(app, ["update", "--help"])

    assert result.exit_code == 0
    assert "--industry-symbol" in result.output
    assert "--request-interval" in result.output
    assert "--retry" in result.output
    assert "--industry-batch-size" in result.output
    assert "--industry-file" in result.output


def test_update_stock_industry_accepts_local_industry_file(tmp_path: Path) -> None:
    """stock-industry should support local mapping files without network access."""
    sample_path = tmp_path / "sample.csv"
    db_path = tmp_path / "fund_research.sqlite"
    industry_path = tmp_path / "stock_industry_sw.csv"
    _write_sample(sample_path)
    industry_path.write_text(
        "\n".join([
            "stock_code,stock_name,industry_name,effective_date",
            "600519.SH,贵州茅台,食品饮料,2026-06-01",
        ]),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "update",
            "--domains",
            "stock-industry",
            "--industry-file",
            str(industry_path),
            "--sample",
            str(sample_path),
            "--db-path",
            str(db_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "stock_industry" in result.output
    assert "DRY-RUN" in result.output
