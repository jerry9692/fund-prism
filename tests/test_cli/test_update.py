"""CLI update tests."""

from pathlib import Path

import pytest
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
        "benchmark-members,stock-industry,benchmark-industry,benchmark-validation,holding-industry",
    )

    assert selected == [
        "benchmark-members",
        "stock-industry",
        "benchmark-industry",
        "benchmark-validation-import",
        "holding-industry-backfill",
    ]


def test_update_help_includes_stock_industry_stability_options() -> None:
    """stock-industry should expose controls for segmented, throttled updates."""
    result = CliRunner().invoke(app, ["update", "--help"])

    assert result.exit_code == 0
    assert "--benchmark-members-file" in result.output
    assert "--industry-symbol" in result.output
    assert "--request-interval" in result.output
    assert "--retry" in result.output
    assert "--industry-batch-size" in result.output
    assert "--industry-file" in result.output
    assert "--benchmark-validation-db" in result.output
    assert "--overwrite-holding-industry" in result.output


def test_update_benchmark_members_accepts_local_member_file(tmp_path: Path) -> None:
    """benchmark-members should support a local constituent weight file."""
    sample_path = tmp_path / "sample.csv"
    db_path = tmp_path / "fund_research.sqlite"
    member_path = tmp_path / "000300closeweight.csv"
    _write_sample(sample_path)
    member_path.write_text(
        "\n".join([
            "日期,指数代码,指数名称,成分券代码,成分券名称,交易所,权重",
            "2026-06-01,000300,沪深300,600519.SH,贵州茅台,上海证券交易所,5.25",
        ]),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "update",
            "--domains",
            "benchmark-members",
            "--index-symbol",
            "sh000300",
            "--benchmark-members-file",
            str(member_path),
            "--sample",
            str(sample_path),
            "--db-path",
            str(db_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "benchmark_index" in result.output
    assert "DRY-RUN" in result.output


def test_update_benchmark_members_file_requires_single_index_symbol(tmp_path: Path) -> None:
    """A local benchmark member file must map to exactly one benchmark symbol."""
    sample_path = tmp_path / "sample.csv"
    db_path = tmp_path / "fund_research.sqlite"
    member_path = tmp_path / "000300closeweight.csv"
    _write_sample(sample_path)
    member_path.write_text("日期,成分券代码,权重\n2026-06-01,600519,5.25", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "update",
            "--domains",
            "benchmark-members",
            "--benchmark-members-file",
            str(member_path),
            "--sample",
            str(sample_path),
            "--db-path",
            str(db_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 1
    assert "--benchmark-members-file" in result.output


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


# ============================================================
# P4.1-2: 指数数据域 — 申万行业指数路由
# ============================================================


def _patch_index_domain_upserts(monkeypatch: pytest.MonkeyPatch) -> dict[str, set[str]]:
    """Patch P4.1-2 upsert entry points so CLI routing can be tested offline."""
    import fund_research.data.update as update_module
    from fund_research.data.update import UpdateSummary

    calls: dict[str, set[str]] = {"sw_daily": set(), "market_daily": set(), "sw_members": set()}

    def fake_sw_daily(session, index_symbols, *, start_date=None, end_date=None, dry_run=False, **kwargs):
        calls["sw_daily"].update(index_symbols)
        return UpdateSummary(
            entity="index_daily", source="akshare", requested=len(index_symbols), dry_run=dry_run
        )

    def fake_market_daily(session, index_symbols, *, start_date=None, end_date=None, dry_run=False, **kwargs):
        calls["market_daily"].update(index_symbols)
        return UpdateSummary(
            entity="index_daily", source="akshare", requested=len(index_symbols), dry_run=dry_run
        )

    def fake_sw_members(session, index_symbols, *, dry_run=False, **kwargs):
        calls["sw_members"].update(index_symbols)
        return UpdateSummary(
            entity="index_constituent",
            source="akshare",
            requested=len(index_symbols),
            dry_run=dry_run,
        )

    monkeypatch.setattr(update_module, "upsert_akshare_industry_index_daily", fake_sw_daily)
    monkeypatch.setattr(update_module, "upsert_akshare_index_daily", fake_market_daily)
    monkeypatch.setattr(update_module, "upsert_akshare_index_constituents", fake_sw_members)
    return calls


def test_update_index_daily_routes_sw_symbols_to_index_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SW industry symbols should go through the P4.1-2 index domain pipeline."""
    sample_path = tmp_path / "sample.csv"
    db_path = tmp_path / "fund_research.sqlite"
    _write_sample(sample_path)
    calls = _patch_index_domain_upserts(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "update",
            "index-daily",
            "--index-symbol", "801010.SI",
            "--index-symbol", "sh000300",
            "--sample", str(sample_path),
            "--db-path", str(db_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert calls["sw_daily"] == {"801010.SI"}
    assert calls["market_daily"] == {"sh000300"}
    assert calls["sw_members"] == set()


def test_update_benchmark_members_routes_sw_symbols(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """benchmark-members should route SW symbols to index_constituent."""
    sample_path = tmp_path / "sample.csv"
    db_path = tmp_path / "fund_research.sqlite"
    _write_sample(sample_path)
    calls = _patch_index_domain_upserts(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "update",
            "benchmark-members",
            "--index-symbol", "801010",
            "--sample", str(sample_path),
            "--db-path", str(db_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert calls["sw_members"] == {"801010"}


def test_update_help_includes_industry_index_entity() -> None:
    """industry-index entity should be exposed in the update CLI."""
    result = CliRunner().invoke(app, ["update", "--help"])

    assert result.exit_code == 0
    assert "industry-index" in result.output
    assert "--sw-level" in result.output


# ============================================================
# P4.1-3: 债券数据域 — CLI 路由
# ============================================================


def _patch_bond_domain_upserts(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """Patch P4.1-3 upsert entry points so CLI routing can be tested offline."""
    import fund_research.data.update as update_module
    from fund_research.data.update import UpdateSummary

    calls: dict[str, list] = {
        "cb_list": [],
        "cb_daily": [],
        "china_curve": [],
        "credit_curve": [],
    }

    def fake_cb_list(session, *, adapter=None, dry_run=False, **kwargs):
        calls["cb_list"].append(True)
        return UpdateSummary(entity="bond_main", source="akshare", dry_run=dry_run)

    def fake_cb_daily(session, bond_codes, *, start_date=None, end_date=None, dry_run=False, **kwargs):
        calls["cb_daily"].append(set(bond_codes))
        return UpdateSummary(
            entity="bond_daily", source="akshare", requested=len(bond_codes), dry_run=dry_run
        )

    def fake_china_curve(session, *, adapter=None, start_date=None, end_date=None, dry_run=False, **kwargs):
        calls["china_curve"].append((start_date, end_date))
        return UpdateSummary(entity="yield_curve_daily", source="akshare", dry_run=dry_run)

    def fake_credit_curve(session, *, adapter=None, start_date=None, end_date=None, dry_run=False, **kwargs):
        calls["credit_curve"].append((start_date, end_date))
        return UpdateSummary(entity="yield_curve_daily", source="akshare", dry_run=dry_run)

    monkeypatch.setattr(update_module, "upsert_akshare_cb_list", fake_cb_list)
    monkeypatch.setattr(update_module, "upsert_akshare_cb_daily", fake_cb_daily)
    monkeypatch.setattr(update_module, "upsert_akshare_china_yield_curve", fake_china_curve)
    monkeypatch.setattr(update_module, "upsert_akshare_credit_yield_curve", fake_credit_curve)
    return calls


def test_update_bond_daily_routes_bond_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """bond-daily should pass --bond-code values into the CB daily pipeline."""
    sample_path = tmp_path / "sample.csv"
    db_path = tmp_path / "fund_research.sqlite"
    _write_sample(sample_path)
    calls = _patch_bond_domain_upserts(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "update",
            "bond-daily",
            "--bond-code", "128039",
            "--sample", str(sample_path),
            "--db-path", str(db_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert calls["cb_daily"] == [{"128039"}]
    assert calls["cb_list"] == []
    assert calls["china_curve"] == []


def test_update_bond_domain_runs_full_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """bond-domain one-shot should hit CB list + daily quotes + yield curves."""
    sample_path = tmp_path / "sample.csv"
    db_path = tmp_path / "fund_research.sqlite"
    _write_sample(sample_path)
    calls = _patch_bond_domain_upserts(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "update",
            "bond-domain",
            "--bond-code", "110080",
            "--start", "2023-08-14",
            "--end", "2026-08-14",
            "--sample", str(sample_path),
            "--db-path", str(db_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert calls["cb_list"] == [True]
    assert calls["cb_daily"] == [{"110080"}]
    assert len(calls["china_curve"]) == 1
    assert len(calls["credit_curve"]) == 1


def test_update_help_includes_bond_domain_entities() -> None:
    """Bond domain entities and --bond-code should be exposed in the update CLI."""
    result = CliRunner().invoke(app, ["update", "--help"])

    assert result.exit_code == 0
    assert "--bond-code" in result.output
    # 实体与别名解析（帮助文本受终端折行影响，实体存在性以解析函数验证）
    assert _selected_update_entities("bond-domain", None) == ["bond-domain"]
    assert _selected_update_entities("sample-funds", "bond,yield") == [
        "yield-curve",
        "bond-domain",
    ]
    assert _selected_update_entities("sample-funds", "cb-list,cb-daily") == [
        "bond-main",
        "bond-daily",
    ]
