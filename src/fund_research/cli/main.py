"""
CLI 入口。

提供命令行接口用于：
- 数据库初始化和管理
- 数据源健康检查
- API 服务启动
- 数据更新任务
"""

import csv
import json
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fund_research import __version__
from fund_research.analysis.exposure import DEFAULT_STYLE_FACTORS
from fund_research.utils.logging import setup_logging

app = typer.Typer(
    name="fund-research",
    help="AI-oriented 开源个人基金研究平台 CLI",
    add_completion=False,
)

console = Console()

UPDATE_ENTITY_ORDER = [
    "sample-funds",
    "fund-info",
    "fund-managers",
    "fund-scale",
    "fund-fees",
    "fund-nav",
    "fund-dividends",
    "fund-holdings",
    "fund-industry-allocation",
    "fund-portfolio-change",
    "holder-structure",
    "stock-daily",
    "index-daily",
    "benchmark-members",
    "stock-industry",
    "benchmark-industry",
    "official-pdf",
]
UPDATE_DOMAIN_ALIASES = {
    "sample": "sample-funds",
    "samples": "sample-funds",
    "sample-funds": "sample-funds",
    "profile": "fund-info",
    "fund-info": "fund-info",
    "manager": "fund-managers",
    "managers": "fund-managers",
    "fund-managers": "fund-managers",
    "scale": "fund-scale",
    "fund-scale": "fund-scale",
    "fee": "fund-fees",
    "fees": "fund-fees",
    "fund-fees": "fund-fees",
    "nav": "fund-nav",
    "fund-nav": "fund-nav",
    "dividend": "fund-dividends",
    "dividends": "fund-dividends",
    "fund-dividends": "fund-dividends",
    "holdings": "fund-holdings",
    "fund-holdings": "fund-holdings",
    "industry": "fund-industry-allocation",
    "industry-allocation": "fund-industry-allocation",
    "fund-industry-allocation": "fund-industry-allocation",
    "change": "fund-portfolio-change",
    "changes": "fund-portfolio-change",
    "portfolio-change": "fund-portfolio-change",
    "fund-portfolio-change": "fund-portfolio-change",
    "holder": "holder-structure",
    "holder-structure": "holder-structure",
    "stock": "stock-daily",
    "stock-daily": "stock-daily",
    "index": "index-daily",
    "index-daily": "index-daily",
    "benchmark": "benchmark-members",
    "benchmark-members": "benchmark-members",
    "benchmark-index-member": "benchmark-members",
    "benchmark-index-members": "benchmark-members",
    "benchmark-industry": "benchmark-industry",
    "benchmark-industry-weight": "benchmark-industry",
    "benchmark-industry-weights": "benchmark-industry",
    "stock-industry": "stock-industry",
    "industry-membership": "stock-industry",
    "official-pdf": "official-pdf",
    "pdf": "official-pdf",
    "all": "all",
}

UpdateEntityArg = Annotated[
    str,
    typer.Argument(
        help=(
            "要更新的数据类型 "
            "(sample-funds/fund-info/fund-managers/fund-scale/fund-fees/fund-nav/"
            "fund-dividends/fund-holdings/fund-industry-allocation/"
            "fund-portfolio-change/holder-structure/stock-daily/index-daily/"
            "benchmark-members/stock-industry/benchmark-industry/official-pdf/all)"
        )
    ),
]
FundCodeOption = Annotated[
    list[str] | None,
    typer.Option("--fund-code", "-f", help="只更新指定基金代码，可重复传入"),
]
StockCodeOption = Annotated[
    list[str] | None,
    typer.Option("--stock-code", help="只更新指定股票代码，可重复传入"),
]
IndexSymbolOption = Annotated[
    list[str] | None,
    typer.Option("--index-symbol", help="只更新指定指数 symbol，可重复传入"),
]
BenchmarkMembersFileOption = Annotated[
    Path | None,
    typer.Option("--benchmark-members-file", help="从本地 CSV/XLS/XLSX 导入指数成分权重，需配合单个 --index-symbol"),
]
IndustrySymbolOption = Annotated[
    list[str] | None,
    typer.Option("--industry-symbol", help="只更新指定行业 symbol，可重复传入，如 801120.SI"),
]
IndustryFileOption = Annotated[
    Path | None,
    typer.Option("--industry-file", help="从本地 CSV/XLSX 导入股票行业归属，传入后 stock-industry 不走网络抓取"),
]
SamplePathOption = Annotated[
    Path | None,
    typer.Option("--sample", help="样本基金 CSV 路径；不传则读取 FUND_SAMPLE_FUNDS_PATH"),
]
DbPathOption = Annotated[
    str | None,
    typer.Option("--db-path", "-d", help="数据库文件路径"),
]
DryRunOption = Annotated[
    bool,
    typer.Option("--dry-run", help="只预览更新，不写入数据库"),
]
DomainsOption = Annotated[
    str | None,
    typer.Option("--domains", help="按数据域更新，逗号分隔，如 profile,nav,holdings"),
]
StartDateOption = Annotated[
    str | None,
    typer.Option("--start", "--from", help="净值/行情起始日期 YYYY-MM-DD"),
]
EndDateOption = Annotated[
    str | None,
    typer.Option("--end", "--to", help="净值/行情结束日期 YYYY-MM-DD"),
]
ReportDateOption = Annotated[
    str | None,
    typer.Option("--report-date", help="持仓报告期 YYYY-MM-DD"),
]
YearOption = Annotated[
    int | None,
    typer.Option("--year", help="分红年度 YYYY"),
]
RequestIntervalOption = Annotated[
    float,
    typer.Option("--request-interval", help="批量抓取请求间隔秒数，主要用于 stock-industry"),
]
RetryOption = Annotated[
    int,
    typer.Option("--retry", help="单个数据项失败后的重试次数，主要用于 stock-industry"),
]
IndustryBatchSizeOption = Annotated[
    int,
    typer.Option("--industry-batch-size", help="stock-industry 每批提交的行业数量，0 表示不分批"),
]


def _selected_update_entities(entity: str, domains: str | None) -> list[str]:
    """Resolve positional update entity and optional domain aliases into ordered entities."""
    if domains:
        requested = []
        for raw_domain in domains.split(","):
            domain = raw_domain.strip().lower().replace("_", "-")
            if not domain:
                continue
            mapped = UPDATE_DOMAIN_ALIASES.get(domain)
            if mapped is None:
                raise ValueError(domain)
            if mapped == "all":
                return UPDATE_ENTITY_ORDER.copy()
            requested.append(mapped)
        unique_requested = set(requested)
        return [item for item in UPDATE_ENTITY_ORDER if item in unique_requested]

    normalized_entity = entity.strip().lower().replace("_", "-")
    if normalized_entity == "all":
        return UPDATE_ENTITY_ORDER.copy()
    if normalized_entity not in UPDATE_ENTITY_ORDER:
        raise ValueError(normalized_entity)
    return [normalized_entity]


@app.command()
def version() -> None:
    """显示平台版本号。"""
    console.print(f"[bold green]fund-research[/] v{__version__}")


@app.command()
def init(
    db_path: str = typer.Option(
        "./data/fund_research.duckdb", "--db-path", "-d", help="数据库文件路径"
    ),
) -> None:
    """初始化数据库（创建所有表）。"""
    from sqlalchemy.orm import sessionmaker

    from fund_research.data.metric_registry import seed_metric_registry
    from fund_research.db.session import create_engine_from_path
    from fund_research.db.session import init_db as db_init

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with console.status("[bold cyan]正在初始化数据库..."):
        db_init(db_path)
        engine = create_engine_from_path(db_path)
        session_factory = sessionmaker(bind=engine)
        with session_factory() as session:
            summary = seed_metric_registry(session)

    console.print(f"[green]OK[/] 数据库已初始化: {path.absolute()}")
    console.print(
        "[green]OK[/] 指标注册表已同步: "
        f"inserted={summary.inserted}, updated={summary.updated}, skipped={summary.skipped}"
    )
    console.print("[dim]提示: 使用 'fund-research serve' 启动 API 服务[/dim]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="监听地址"),
    port: int = typer.Option(8000, "--port", "-p", help="监听端口"),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="开发模式热重载"),
) -> None:
    """启动 API 服务。"""
    import uvicorn

    console.print(
        Panel.fit(
            f"[bold]Fund Research API[/]\n"
            f"地址: [cyan]http://{host}:{port}[/cyan]\n"
            f"文档: [cyan]http://{host}:{port}/docs[/cyan]\n"
            f"版本: v{__version__}",
            title="启动信息",
        )
    )
    uvicorn.run(
        "fund_research.api.app:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )


@app.command()
def check_data(
    db_path: DbPathOption = None,
) -> None:
    """检查第零阶段本地产物和一期本地数据库状态。"""
    from fund_research.config.settings import get_settings

    project_root = Path.cwd()
    settings = get_settings()
    configured_sample_path = settings.sample_funds_path_absolute
    checks = [
        ("样本基金", configured_sample_path),
        ("字段映射", project_root / "config" / "field_mapping_v0.1.yaml"),
        ("接口盘点", project_root / "docs" / "phase0" / "akshare-field-inventory-p0.json"),
        ("质量摘要", project_root / "docs" / "phase0" / "quality_baseline_summary.json"),
        ("一期开工验证", project_root / "docs" / "phase0" / "pre_phase1_readiness.json"),
        ("披露粒度", project_root / "docs" / "phase0" / "disclosure_granularity.csv"),
        ("阶段总结", project_root / "docs" / "phase0" / "conclusion.md"),
    ]

    table = Table(title="Phase 0 本地产物检查")
    table.add_column("项目")
    table.add_column("状态")
    table.add_column("说明")

    ok = True
    for name, path in checks:
        exists = path.exists()
        ok = ok and exists
        table.add_row(name, "[green]OK[/]" if exists else "[red]缺失[/]", str(path))

    sample_path = configured_sample_path
    if sample_path.exists():
        with sample_path.open(encoding="utf-8", newline="") as f:
            sample_count = sum(1 for _ in csv.DictReader(f))
        sample_ok = sample_count == 30
        ok = ok and sample_ok
        table.add_row(
            "样本数量",
            "[green]OK[/]" if sample_ok else "[red]异常[/]",
            f"{sample_count}/30",
        )

    quality_path = project_root / "docs" / "phase0" / "quality_baseline_summary.json"
    if quality_path.exists():
        try:
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            failures = quality.get("fetch_failures")
            total_funds = quality.get("total_funds")
            quality_ok = failures == 0 and total_funds == 30
            ok = ok and quality_ok
            table.add_row(
                "质量摘要",
                "[green]OK[/]" if quality_ok else "[yellow]需复核[/]",
                f"total_funds={total_funds}, fetch_failures={failures}",
            )
        except json.JSONDecodeError as exc:
            ok = False
            table.add_row("质量摘要", "[red]异常[/]", f"JSON 解析失败: {exc}")

    readiness_path = project_root / "docs" / "phase0" / "pre_phase1_readiness.json"
    if readiness_path.exists():
        try:
            readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
            ready = readiness.get("pre_phase1_ready") is True
            ok = ok and ready
            table.add_row(
                "一期开工验证",
                "[green]OK[/]" if ready else "[red]未通过[/]",
                (
                    f"required={readiness.get('akshare_required_success_count')}/"
                    f"{readiness.get('akshare_required_total_count')}, "
                    f"official_pdf={readiness.get('official_pdf_ok')}"
                ),
            )
        except json.JSONDecodeError as exc:
            ok = False
            table.add_row("一期开工验证", "[red]异常[/]", f"JSON 解析失败: {exc}")

    try:
        from sqlalchemy import func, inspect, select, text
        from sqlalchemy.orm import sessionmaker

        from fund_research.db.models import Base, DataSourceSnapshot, MetricRegistry, TaskLog
        from fund_research.db.session import create_engine_from_path

        engine = create_engine_from_path(db_path)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        table.add_row(
            "数据库连接",
            "[green]OK[/]",
            db_path or "默认 FUND_DB_PATH / ./data/fund_research.duckdb",
        )

        existing_tables = set(inspect(engine).get_table_names())
        core_tables = set(Base.metadata.tables)
        missing_tables = sorted(core_tables - existing_tables)
        tables_ok = not missing_tables
        ok = ok and tables_ok
        table.add_row(
            "一期核心表",
            "[green]OK[/]" if tables_ok else "[red]缺失[/]",
            (
                f"{len(core_tables)}/{len(core_tables)}"
                if tables_ok
                else f"missing={', '.join(missing_tables[:5])}"
            ),
        )

        if "task_log" in existing_tables:
            session_factory = sessionmaker(bind=engine)
            with session_factory() as session:
                metric_count = session.scalar(
                    select(func.count())
                    .select_from(MetricRegistry)
                    .where(MetricRegistry.is_active.is_(True))
                )
                snapshots = session.scalars(select(DataSourceSnapshot)).all()
                latest_snapshots: dict[tuple[str, str], DataSourceSnapshot] = {}
                for snapshot in snapshots:
                    key = (snapshot.entity_type, snapshot.source_name)
                    previous = latest_snapshots.get(key)
                    if previous is None or snapshot.fetch_timestamp > previous.fetch_timestamp:
                        latest_snapshots[key] = snapshot
                failed_snapshots = sum(
                    1 for snapshot in latest_snapshots.values() if not snapshot.is_success
                )
                failed_tasks = session.scalar(
                    select(func.count())
                    .select_from(TaskLog)
                    .where(TaskLog.status == "failed")
                )
            metric_ok = bool(metric_count)
            ok = ok and metric_ok
            table.add_row(
                "指标注册表",
                "[green]OK[/]" if metric_ok else "[red]为空[/]",
                f"active={metric_count}",
            )
            snapshots_ok = failed_snapshots == 0
            ok = ok and snapshots_ok
            table.add_row(
                "失败快照",
                "[green]OK[/]" if snapshots_ok else "[red]异常[/]",
                f"failed={failed_snapshots}",
            )
            tasks_ok = failed_tasks == 0
            ok = ok and tasks_ok
            table.add_row(
                "失败任务",
                "[green]OK[/]" if tasks_ok else "[red]异常[/]",
                f"failed={failed_tasks}",
            )
        else:
            ok = False
            table.add_row("失败任务", "[red]无法检查[/]", "task_log 表缺失")
    except Exception as exc:
        ok = False
        table.add_row("数据库检查", "[red]异常[/]", str(exc))

    console.print(table)
    if ok:
        console.print("[green]OK[/] Phase 0 本地产物与一期数据库检查通过")
    else:
        raise typer.Exit(code=1)


@app.command()
def update(
    entity: UpdateEntityArg = "sample-funds",
    fund_code: FundCodeOption = None,
    stock_code: StockCodeOption = None,
    index_symbol: IndexSymbolOption = None,
    benchmark_members_file: BenchmarkMembersFileOption = None,
    industry_symbol: IndustrySymbolOption = None,
    industry_file: IndustryFileOption = None,
    sample: SamplePathOption = None,
    db_path: DbPathOption = None,
    dry_run: DryRunOption = False,
    domains: DomainsOption = None,
    start: StartDateOption = None,
    end: EndDateOption = None,
    report_date: ReportDateOption = None,
    year: YearOption = None,
    request_interval: RequestIntervalOption = 0.0,
    retry: RetryOption = 0,
    industry_batch_size: IndustryBatchSizeOption = 20,
) -> None:
    """更新本地数据。"""
    from sqlalchemy.orm import sessionmaker

    from fund_research.config.settings import get_settings
    from fund_research.data.update import (
        UpdateSummary,
        latest_holding_stock_codes,
        load_sample_funds,
        upsert_akshare_benchmark_index_members,
        upsert_akshare_fund_dividends,
        upsert_akshare_fund_fees,
        upsert_akshare_fund_holdings,
        upsert_akshare_fund_industry_allocation,
        upsert_akshare_fund_info,
        upsert_akshare_fund_managers,
        upsert_akshare_fund_nav,
        upsert_akshare_fund_portfolio_changes,
        upsert_akshare_fund_scale,
        upsert_akshare_holder_structure,
        upsert_akshare_index_daily,
        upsert_akshare_official_pdf_evidence,
        upsert_akshare_stock_daily,
        upsert_akshare_stock_industry_membership,
        upsert_benchmark_industry_weights,
        upsert_local_benchmark_index_members,
        upsert_local_stock_industry_membership,
        upsert_sample_funds,
    )
    from fund_research.db.session import create_engine_from_path, init_db

    try:
        selected_entities = _selected_update_entities(entity, domains)
    except ValueError as exc:
        console.print(f"[red]暂不支持的数据类型:[/] {exc}")
        raise typer.Exit(code=1) from None

    settings = get_settings()
    sample = sample or settings.sample_funds_path_absolute
    if not sample.exists():
        console.print(f"[red]样本文件不存在:[/] {sample}")
        raise typer.Exit(code=1)

    init_db(db_path)
    engine = create_engine_from_path(db_path)
    session_factory = sessionmaker(bind=engine)
    selected_codes = set(fund_code) if fund_code else {
        row.get("fund_code", "").strip()
        for row in load_sample_funds(sample)
        if row.get("fund_code", "").strip()
    }
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    holding_report_date = date.fromisoformat(report_date) if report_date else None
    summaries: list[UpdateSummary] = []
    with session_factory() as session:
        if "sample-funds" in selected_entities:
            summaries.append(
                upsert_sample_funds(
                    session,
                    sample,
                    fund_codes=set(fund_code) if fund_code else None,
                    dry_run=dry_run,
                )
            )
        if "fund-info" in selected_entities:
            summaries.append(
                upsert_akshare_fund_info(session, selected_codes, dry_run=dry_run)
            )
        if "fund-managers" in selected_entities:
            summaries.append(
                upsert_akshare_fund_managers(session, selected_codes, dry_run=dry_run)
            )
        if "fund-scale" in selected_entities:
            summaries.append(
                upsert_akshare_fund_scale(session, selected_codes, dry_run=dry_run)
            )
        if "fund-fees" in selected_entities:
            summaries.append(
                upsert_akshare_fund_fees(session, selected_codes, dry_run=dry_run)
            )
        if "fund-nav" in selected_entities:
            summaries.append(
                upsert_akshare_fund_nav(
                    session,
                    selected_codes,
                    start_date=start_date,
                    end_date=end_date,
                    dry_run=dry_run,
                )
            )
        if "fund-dividends" in selected_entities:
            summaries.append(
                upsert_akshare_fund_dividends(
                    session,
                    selected_codes,
                    year=year,
                    dry_run=dry_run,
                )
            )
        if "fund-holdings" in selected_entities:
            summaries.append(
                upsert_akshare_fund_holdings(
                    session,
                    selected_codes,
                    report_date=holding_report_date,
                    dry_run=dry_run,
                )
            )
        if "fund-industry-allocation" in selected_entities:
            summaries.append(
                upsert_akshare_fund_industry_allocation(
                    session,
                    selected_codes,
                    report_date=holding_report_date,
                    dry_run=dry_run,
                )
            )
        if "fund-portfolio-change" in selected_entities:
            summaries.append(
                upsert_akshare_fund_portfolio_changes(
                    session,
                    selected_codes,
                    report_date=holding_report_date,
                    dry_run=dry_run,
                )
            )
        if "holder-structure" in selected_entities:
            summaries.append(
                upsert_akshare_holder_structure(session, selected_codes, dry_run=dry_run)
            )
        if "stock-daily" in selected_entities:
            selected_stock_codes = set(stock_code) if stock_code else latest_holding_stock_codes(
                session,
                selected_codes,
            )
            if selected_stock_codes:
                summaries.append(
                    upsert_akshare_stock_daily(
                        session,
                        selected_stock_codes,
                        start_date=start_date,
                        end_date=end_date,
                        dry_run=dry_run,
                    )
                )
            else:
                summaries.append(
                    UpdateSummary(
                        entity="stock_daily",
                        source="akshare",
                        requested=0,
                        dry_run=dry_run,
                        warnings=["未指定股票代码，且本地最新持仓中没有可更新的股票代码"],
                    )
                )
        if "index-daily" in selected_entities:
            selected_index_symbols = set(index_symbol) if index_symbol else set(
                DEFAULT_STYLE_FACTORS.values()
            )
            summaries.append(
                upsert_akshare_index_daily(
                    session,
                    selected_index_symbols,
                    start_date=start_date,
                    end_date=end_date,
                    dry_run=dry_run,
                )
            )
        if "benchmark-members" in selected_entities:
            selected_index_symbols = set(index_symbol) if index_symbol else {
                "sh000300",
                "sh000905",
                "sh000852",
            }
            if benchmark_members_file is not None:
                if len(selected_index_symbols) != 1:
                    console.print("[red]--benchmark-members-file 需要配合且只配合一个 --index-symbol[/]")
                    raise typer.Exit(code=1)
                summaries.append(
                    upsert_local_benchmark_index_members(
                        session,
                        next(iter(selected_index_symbols)),
                        benchmark_members_file,
                        dry_run=dry_run,
                    )
                )
            else:
                summaries.append(
                    upsert_akshare_benchmark_index_members(
                        session,
                        selected_index_symbols,
                        dry_run=dry_run,
                    )
                )
        if "stock-industry" in selected_entities:
            if industry_file is not None:
                summaries.append(
                    upsert_local_stock_industry_membership(
                        session,
                        industry_file,
                        dry_run=dry_run,
                    )
                )
            else:
                summaries.append(
                    upsert_akshare_stock_industry_membership(
                        session,
                        set(industry_symbol) if industry_symbol else None,
                        request_interval_seconds=max(request_interval, 0.0),
                        max_retries=max(retry, 0),
                        industry_batch_size=max(industry_batch_size, 0),
                        symbol_cache_dir=settings.cache_dir_absolute,
                        dry_run=dry_run,
                    )
                )
        if "benchmark-industry" in selected_entities:
            selected_index_symbols = set(index_symbol) if index_symbol else {
                "sh000300",
                "sh000905",
                "sh000852",
            }
            summaries.append(
                upsert_benchmark_industry_weights(
                    session,
                    selected_index_symbols,
                    target_date=end_date,
                    dry_run=dry_run,
                )
            )
        if "official-pdf" in selected_entities:
            summaries.append(
                upsert_akshare_official_pdf_evidence(
                    session,
                    selected_codes,
                    dry_run=dry_run,
                )
            )

    table = Table(title="数据更新摘要")
    table.add_column("entity")
    table.add_column("requested")
    table.add_column("inserted")
    table.add_column("updated")
    table.add_column("skipped")
    table.add_column("warnings")
    for summary in summaries:
        data = summary.to_dict()
        table.add_row(
            str(data["entity"]),
            str(data["requested"]),
            str(data["inserted"]),
            str(data["updated"]),
            str(data["skipped"]),
            json.dumps(data["warnings"], ensure_ascii=False),
        )

    console.print(table)
    if dry_run:
        console.print("[yellow]DRY-RUN[/] 未写入数据库")
    else:
        console.print("[green]OK[/] 数据更新完成")


# ============================================================
# export — 结构化导出
# ============================================================

ExportFormatOption = Annotated[
    str,
    typer.Option("--format", help="导出格式: json / markdown / csv"),
]
ExportOutputOption = Annotated[
    str | None,
    typer.Option("--output", "-o", help="输出文件路径；不传则输出到 ./exports/"),
]
ExportLatestOption = Annotated[
    bool,
    typer.Option("--latest", help="导出最新研究包（无需指定 packet_id）"),
]
ExportPacketIdOption = Annotated[
    str | None,
    typer.Option("--packet-id", help="指定研究包 ID"),
]
ExportFiltersOption = Annotated[
    str | None,
    typer.Option("--filters", help="筛选条件 JSON（screen 导出用）"),
]


@app.command()
def export(
    entity: Annotated[
        str,
        typer.Argument(help="导出类型: packet / screen"),
    ],
    fund_code: FundCodeOption = None,
    format: ExportFormatOption = "markdown",
    output: ExportOutputOption = None,
    latest: ExportLatestOption = False,
    packet_id: ExportPacketIdOption = None,
    filters: ExportFiltersOption = None,
    db_path: DbPathOption = None,
) -> None:
    """导出研究包或筛选结果。"""
    import json as _json
    from datetime import datetime
    from pathlib import Path as _Path

    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from fund_research.config.settings import get_settings
    from fund_research.db.models import ResearchPacketRecord
    from fund_research.db.session import create_engine_from_path

    engine = create_engine_from_path(db_path)
    session_factory = sessionmaker(bind=engine)

    output_path = _Path(output) if output else None

    def _resolve_output(default_name: str) -> _Path:
        if output_path is None:
            out_dir = _Path("./exports")
            out_dir.mkdir(parents=True, exist_ok=True)
            return out_dir / default_name
        if output_path.suffix:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            return output_path
        output_path.mkdir(parents=True, exist_ok=True)
        return output_path / default_name

    with session_factory() as session:
        if entity == "packet":
            record = None
            if packet_id:
                record = session.scalar(
                    select(ResearchPacketRecord).where(ResearchPacketRecord.packet_id == packet_id)
                )
            elif latest and fund_code:
                record = session.scalar(
                    select(ResearchPacketRecord).where(
                        ResearchPacketRecord.fund_code == fund_code[0],
                        ResearchPacketRecord.is_latest,
                    )
                )
            elif fund_code:
                record = session.scalar(
                    select(ResearchPacketRecord).where(
                        ResearchPacketRecord.fund_code == fund_code[0]
                    ).order_by(ResearchPacketRecord.generated_at.desc()).limit(1)
                )

            if not record:
                console.print("[red]未找到研究包[/]")
                raise typer.Exit(code=1)

            fc = fund_code[0] if fund_code else record.fund_code
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")

            def _source_levels(rec) -> str:
                if not isinstance(rec.packet_json, dict):
                    return "N/A"
                return ", ".join(
                    rec.packet_json.get("metadata", {}).get("data_source_levels", [])
                )

            if format == "json":
                out_path = _resolve_output(f"{fc}_packet_{ts}.json")
                content = _json.dumps(record.packet_json, ensure_ascii=False, indent=2)
                out_path.write_text(content, encoding="utf-8")
                console.print(f"[green]JSON 已导出:[/] {out_path}")

            elif format == "markdown":
                out_path = _resolve_output(f"{fc}_packet_{ts}.md")
                disclaimer = get_settings().disclaimer
                md = record.markdown_text or ""
                header = (
                    f"# 基金研究包: {fc}\n\n"
                    f"> 生成日期: {record.generated_at.date().isoformat() if record.generated_at else 'N/A'}"
                    f" | 数据日期: {record.data_date}\n"
                    f"> 平台版本: {record.platform_version}"
                    f" | 数据源等级: {_source_levels(record)}\n"
                    f"> 整体置信度: {record.overall_confidence}\n"
                    f"> 免责声明: {disclaimer}\n\n---\n\n"
                )
                content = header + md
                out_path.write_text(content, encoding="utf-8")
                console.print(f"[green]Markdown 已导出:[/] {out_path}")

            else:
                console.print(f"[red]不支持的格式:[/] {format}")
                raise typer.Exit(code=1)

        elif entity == "screen":
            if format != "csv":
                console.print("[yellow]screen 导出仅支持 CSV 格式，已自动切换[/]")
                format = "csv"

            out_path = _resolve_output(f"screen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            filter_dict = _json.loads(filters) if filters else {}
            from fund_research.api.router import screen_funds as _screen

            result = _screen(session, filter_dict)
            funds = (result.data or {}).get("funds", [])
            if not funds:
                console.print("[yellow]无筛选结果[/]")
                raise typer.Exit(code=0)

            import csv
            with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=funds[0].keys())
                writer.writeheader()
                writer.writerows(funds)
            console.print(f"[green]CSV 已导出:[/] {out_path} ({len(funds)} 条)")

        else:
            console.print(f"[red]不支持的导出类型:[/] {entity}")
            raise typer.Exit(code=1)


@app.callback()
def main(
    log_level: str = typer.Option("INFO", "--log-level", "-l", help="日志级别"),
    log_file: str = typer.Option("./logs/fund_research.log", "--log-file", help="日志文件路径"),
) -> None:
    """fund-research CLI — AI-oriented 开源个人基金研究平台。"""
    setup_logging(log_level=log_level, log_file=log_file)


if __name__ == "__main__":
    app()
