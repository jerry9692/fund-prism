"""CLI update tests."""

from pathlib import Path

from typer.testing import CliRunner

from fund_research.cli.main import app


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
