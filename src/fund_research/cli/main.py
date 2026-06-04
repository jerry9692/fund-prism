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
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fund_research import __version__
from fund_research.utils.logging import setup_logging

app = typer.Typer(
    name="fund-research",
    help="AI-oriented 开源个人基金研究平台 CLI",
    add_completion=False,
)

console = Console()


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
    from fund_research.db.session import init_db as db_init

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with console.status("[bold cyan]正在初始化数据库..."):
        db_init(db_path)

    console.print(f"[green]✓[/] 数据库已初始化: {path.absolute()}")
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
def check_data() -> None:
    """检查第零阶段本地产物状态。"""
    project_root = Path.cwd()
    checks = [
        ("样本基金", project_root / "data" / "samples" / "sample_funds_v0.1.csv"),
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

    sample_path = project_root / "data" / "samples" / "sample_funds_v0.1.csv"
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

    console.print(table)
    if ok:
        console.print("[green]OK[/] Phase 0 本地产物检查通过")
    else:
        raise typer.Exit(code=1)


@app.command()
def update(
    entity: str = typer.Argument("all", help="要更新的数据类型 (fund_list/fund_nav/all)"),
) -> None:
    """更新本地数据。"""
    console.print("[bold yellow]数据更新功能将在一期数据适配器阶段实现[/bold yellow]")
    console.print(f"请求更新: {entity}")


@app.callback()
def main(
    log_level: str = typer.Option("INFO", "--log-level", "-l", help="日志级别"),
    log_file: str = typer.Option("./logs/fund_research.log", "--log-file", help="日志文件路径"),
) -> None:
    """fund-research CLI — AI-oriented 开源个人基金研究平台。"""
    setup_logging(log_level=log_level, log_file=log_file)


if __name__ == "__main__":
    app()
