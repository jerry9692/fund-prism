"""后台数据更新模块。

启动时在后台线程中静默更新基金净值和指数日线数据，
不阻塞 API 服务。前端通过 /api/v1/system/update-status 轮询状态。

采用 SWR（Stale-While-Revalidate）模式：
- 服务立即启动，先用数据库中的旧数据响应请求
- 后台线程静默拉取最新数据写入数据库
- 前端轮询状态，更新完成后自动刷新页面数据

新鲜度策略：启动前先检查数据库最新交易日，如果数据已经是最新
（>= 预期最近交易日），直接标记为 done 跳过网络请求，
避免每次启动都调用 AKShare。
"""

from __future__ import annotations

import threading
from datetime import date, datetime, time, timedelta
from enum import Enum

from sqlalchemy import func, select

from fund_research.db.models import FundNAV, StockDaily
from fund_research.utils.logging import logger


class UpdateState(str, Enum):
    IDLE = "idle"
    UPDATING = "updating"
    DONE = "done"
    ERROR = "error"


class _UpdateStatus:
    """线程安全的数据更新状态。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: UpdateState = UpdateState.IDLE
        self._message: str = ""
        self._started_at: datetime | None = None
        self._finished_at: datetime | None = None

    @property
    def state(self) -> UpdateState:
        with self._lock:
            return self._state

    @property
    def message(self) -> str:
        with self._lock:
            return self._message

    @property
    def started_at(self) -> datetime | None:
        with self._lock:
            return self._started_at

    @property
    def finished_at(self) -> datetime | None:
        with self._lock:
            return self._finished_at

    def start(self, message: str = "正在更新数据…") -> None:
        with self._lock:
            self._state = UpdateState.UPDATING
            self._message = message
            self._started_at = datetime.now()
            self._finished_at = None

    def update_message(self, message: str) -> None:
        """更新进度消息（不改变状态）。"""
        with self._lock:
            self._message = message

    def finish(self, message: str) -> None:
        with self._lock:
            self._state = UpdateState.DONE
            self._message = message
            self._finished_at = datetime.now()

    def fail(self, message: str) -> None:
        with self._lock:
            self._state = UpdateState.ERROR
            self._message = message
            self._finished_at = datetime.now()

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "state": self._state.value,
                "message": self._message,
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "finished_at": self._finished_at.isoformat() if self._finished_at else None,
            }


# 全局单例
update_status = _UpdateStatus()


def _expected_latest_trade_date(now: datetime | None = None) -> date:
    """计算当前时刻预期的"最新交易日"。

    规则（简化，不精确处理法定节假日）：
    - 工作日 15:00 前：最新交易日应为昨天（周一早上推到上周五）
    - 工作日 15:00 后：最新交易日应为今天
    - 周六/周日：最新交易日应为上周五
    """
    now = now or datetime.now()
    today = now.date()
    weekday = today.weekday()  # 0=Mon, 5=Sat, 6=Sun
    market_close = time(15, 0)

    if weekday == 5:  # Sat
        return today - timedelta(days=1)
    if weekday == 6:  # Sun
        return today - timedelta(days=2)
    if now.time() < market_close:
        if weekday == 0:  # Mon morning -> last Fri
            return today - timedelta(days=3)
        return today - timedelta(days=1)
    return today


def _check_data_freshness() -> tuple[bool, date | None, date | None]:
    """检查数据库中的基金净值和指数日线是否已达到预期最新交易日。

    Returns:
        (is_fresh, latest_nav_date, latest_index_date)
        is_fresh=True 表示两类数据都已最新，可以跳过更新。
    """
    from fund_research.db.session import get_session_factory

    expected = _expected_latest_trade_date()
    session_factory = get_session_factory()
    with session_factory() as session:
        latest_nav = session.scalar(select(func.max(FundNAV.trade_date)))
        latest_idx = session.scalar(select(func.max(StockDaily.trade_date)))

    nav_fresh = latest_nav is not None and latest_nav >= expected
    idx_fresh = latest_idx is not None and latest_idx >= expected
    return (nav_fresh and idx_fresh, latest_nav, latest_idx)


def _do_background_update() -> None:
    """在后台线程中执行数据更新。

    复用主进程的 session_factory 单例，避免创建多余的引擎连接池。
    更新前先做新鲜度检查：数据已是最新则跳过网络请求。
    """
    from fund_research.config.settings import get_settings
    from fund_research.data.update import (
        UpdateSummary,
        load_sample_funds,
        upsert_akshare_fund_nav,
        upsert_akshare_index_daily,
    )

    try:
        # 0. 新鲜度检查：数据已是最新则直接跳过
        update_status.update_message("正在检查数据新鲜度…")
        is_fresh, latest_nav, latest_idx = _check_data_freshness()
        expected = _expected_latest_trade_date()
        if is_fresh:
            msg = f"数据已是最新（净值 {latest_nav}，指数 {latest_idx}）"
            logger.info(f"后台更新: {msg}，跳过请求")
            update_status.finish(msg)
            return
        logger.info(
            f"后台更新: 数据不是最新 (nav={latest_nav}, idx={latest_idx}, "
            f"expected>={expected})，开始拉取"
        )

        settings = get_settings()
        sample_path = settings.sample_funds_path_absolute
        if not sample_path.exists():
            update_status.fail("样本基金文件不存在，跳过更新")
            return

        selected_codes = {
            row.get("fund_code", "").strip()
            for row in load_sample_funds(sample_path)
            if row.get("fund_code", "").strip()
        }
        if not selected_codes:
            update_status.fail("样本基金列表为空，跳过更新")
            return

        from fund_research.db.session import get_session_factory
        session_factory = get_session_factory()

        # 1. 更新基金净值
        update_status.update_message("正在更新基金净值…")
        logger.info("后台更新: 基金净值…")
        with session_factory() as session:
            nav_summary: UpdateSummary = upsert_akshare_fund_nav(
                session, selected_codes, dry_run=False,
            )
        nav_msg = f"净值: +{nav_summary.inserted} 条更新"
        logger.info(f"后台更新净值完成: {nav_msg}")

        # 2. 更新指数日线
        update_status.update_message("正在更新指数行情…")
        logger.info("后台更新: 指数日线…")
        from fund_research.analysis.exposure import DEFAULT_STYLE_FACTORS

        index_symbols = set(DEFAULT_STYLE_FACTORS.values())
        with session_factory() as session:
            idx_summary: UpdateSummary = upsert_akshare_index_daily(
                session, index_symbols, dry_run=False,
            )
        idx_msg = f"指数: +{idx_summary.inserted} 条更新"
        logger.info(f"后台更新指数完成: {idx_msg}")

        summary = f"{nav_msg}；{idx_msg}"
        update_status.finish(summary)
        logger.info(f"后台更新完成: {summary}")

    except Exception as exc:
        logger.error(f"后台数据更新失败: {exc}")
        update_status.fail(f"更新失败: {exc}")


def start_background_update() -> None:
    """启动后台数据更新线程（非阻塞）。"""
    if update_status.state == UpdateState.UPDATING:
        logger.info("后台更新已在进行中，跳过")
        return
    update_status.start("正在连接数据源…")
    thread = threading.Thread(target=_do_background_update, daemon=True, name="bg-data-update")
    thread.start()
    logger.info("后台数据更新线程已启动")
