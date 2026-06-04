"""
日志配置。

使用 loguru 作为日志框架，支持控制台和文件输出。
"""

import sys
from pathlib import Path

from loguru import logger

CONSOLE_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

FILE_LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
)


def setup_logging(
    log_level: str = "INFO",
    log_file: str | None = None,
    rotation: str = "10 MB",
    retention: str = "30 days",
) -> None:
    """配置日志系统。

    Args:
        log_level: 日志级别（DEBUG/INFO/WARNING/ERROR）
        log_file: 日志文件路径（None = 仅控制台输出）
        rotation: 日志文件轮转策略
        retention: 日志文件保留时间
    """
    # 移除默认的 loguru handler
    logger.remove()

    # 控制台输出（彩色，适合开发）
    logger.add(
        sys.stderr,
        level=log_level,
        format=CONSOLE_LOG_FORMAT,
        colorize=True,
    )

    # 文件输出（如配置）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(log_path),
            level=log_level,
            format=FILE_LOG_FORMAT,
            rotation=rotation,
            retention=retention,
            encoding="utf-8",
        )

    logger.info(f"日志系统已初始化（level={log_level}, file={log_file or 'console only'}）")
