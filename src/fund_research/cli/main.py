"""
CLI 入口。

提供命令行接口用于：
- 数据库初始化和管理
- 数据源健康检查
- API 服务启动
- 数据更新任务
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

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
    """检查数据源健康状态。"""
    console.print("[bold yellow]数据源健康检查功能将在第零阶段实现[/bold yellow]")
    console.print("计划检查: AKShare 可达性、本地数据文件完整性、API 响应时间")


@app.command()
def update(
    entity: str = typer.Argument("all", help="要更新的数据类型 (fund_list/fund_nav/all)"),
) -> None:
    """更新本地数据。"""
    console.print(f"[bold yellow]数据更新功能将在第零阶段实现[/bold yellow]")
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
