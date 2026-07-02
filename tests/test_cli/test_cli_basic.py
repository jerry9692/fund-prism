"""CLI basic integration tests — help output and command discovery."""

from typer.testing import CliRunner

from fund_research.cli.main import app


def test_cli_help_shows_app_name_and_commands() -> None:
    """fund-research --help 应输出工具名称和可用命令列表。"""
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "fund-research" in result.output
    assert "init" in result.output
    assert "serve" in result.output


def test_init_help_shows_options() -> None:
    """fund-research init --help 应输出 init 子命令的选项说明。"""
    result = CliRunner().invoke(app, ["init", "--help"])

    assert result.exit_code == 0
    assert "init" in result.output
    assert "--db-path" in result.output


def test_serve_help_shows_options() -> None:
    """fund-research serve --help 应输出 serve 子命令的选项说明。"""
    result = CliRunner().invoke(app, ["serve", "--help"])

    assert result.exit_code == 0
    assert "serve" in result.output
    assert "--port" in result.output
    assert "--host" in result.output


def test_update_help_shows_options() -> None:
    """fund-research update --help 应输出数据更新相关选项。"""
    result = CliRunner().invoke(app, ["update", "--help"])

    assert result.exit_code == 0
    assert "update" in result.output
    assert "ENTITY" in result.output
    assert "--fund-code" in result.output
    assert "--dry-run" in result.output
