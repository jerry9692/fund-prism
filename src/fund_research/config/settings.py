"""
平台全局配置。

使用 pydantic-settings 从 .env 文件和环境变量读取配置。
所有配置项均有默认值，确保本地开箱即用。
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """基金研究平台全局配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FUND_",
        extra="ignore",
    )

    # --- 数据存储 ---
    db_path: str = "./data/fund_research.duckdb"
    cache_dir: str = "./data/cache"
    sample_funds_path: str = "./data/samples/sample_funds_v0.1.csv"

    # --- 日志 ---
    log_level: str = "INFO"
    log_file: str = "./logs/fund_research.log"

    # --- Web API ---
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_reload: bool = True

    # --- 任务调度 ---
    task_max_workers: int = 2

    # --- 数据源 ---
    tushare_token: str = ""
    source_timeout_seconds: float = 20.0
    source_retry_count: int = 2

    # --- 免责声明 ---
    disclaimer: str = "本平台所有算法结果仅用于个人研究和方法验证，不构成投资建议。"

    # --- 算法常量 ---
    trading_days_per_year: int = 252
    risk_free_rate: float = 0.02
    min_nav_observations: int = 60
    min_holdings_for_attribution: int = 10
    default_benchmark: str = "sh000300"

    @property
    def db_path_absolute(self) -> Path:
        """数据库文件的绝对路径。"""
        path = Path(self.db_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def cache_dir_absolute(self) -> Path:
        """缓存目录的绝对路径。"""
        path = Path(self.cache_dir)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def sample_funds_path_absolute(self) -> Path:
        """默认样本基金文件的绝对路径。"""
        path = Path(self.sample_funds_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path

    @property
    def logs_dir_absolute(self) -> Path:
        """日志目录的绝对路径。"""
        path = Path(self.log_file).parent
        if not path.is_absolute():
            path = Path.cwd() / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def platform_version(self) -> str:
        """平台版本号。"""
        from fund_research import __version__

        return __version__


# 全局单例
_settings: Settings | None = None


def get_settings() -> Settings:
    """获取全局配置单例。"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
