// ETF 组合构建（P4D，需求书 §6.2.9）
// CVXPY 二次规划最小化跟踪误差（Ledoit-Wolf 收缩）+ 再平衡回测 + 约束逐条回显

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  type EtfPortfolioConstraint,
  type EtfPortfolioItem,
  type EtfPortfolioBuildBody,
} from "../api/client";
import {
  Breadcrumb,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  SectionHeader,
  StatusBadge,
  type BreadcrumbItem,
} from "../components/display";
import { DataTable, type Column } from "../components/data/DataTable";
import { ChartWrapper } from "../components/data/ChartWrapper";

const BREADCRUMB: BreadcrumbItem[] = [{ label: "ETF 组合构建" }];

const TARGET_OPTIONS: Array<{ symbol: string; label: string }> = [
  { symbol: "sh000300", label: "沪深300" },
  { symbol: "sh000905", label: "中证500" },
  { symbol: "sh000852", label: "中证1000" },
  { symbol: "sh000016", label: "上证50" },
  { symbol: "sz399006", label: "创业板指" },
];

function fmtPct(v: number | string | null | undefined, digits = 2): string {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN;
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

function fmtNum(v: number | string | null | undefined, digits = 2): string {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN;
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

interface MemberRow {
  fund_code: string;
  weight: number;
  fund_name: string | null;
  fee_pct: number | null;
  scale: number | null;
  avg_daily_amount: number | null;
  tracking_error_1y: number | null;
}

export default function EtfPortfolioBuildPage() {
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EtfPortfolioItem | null>(null);

  // 参数表单
  const [targetSymbol, setTargetSymbol] = useState("sh000300");
  const [lookbackDays, setLookbackDays] = useState(252);
  const [rebalanceFrequency, setRebalanceFrequency] = useState("quarterly");
  const [maxWeight, setMaxWeight] = useState(1.0);
  const [maxPositions, setMaxPositions] = useState<string>("");
  const [minScale, setMinScale] = useState<string>("");
  const [maxFee, setMaxFee] = useState<string>("");
  const [maxTurnover, setMaxTurnover] = useState<string>("");

  const loadLatest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getLatestEtfPortfolios();
      const first = res.data?.results?.[0] ?? null;
      setResult(first);
      if (first) setTargetSymbol(first.target_symbol);
    } catch (e) {
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLatest();
  }, [loadLatest]);

  async function handleBuild() {
    setRunning(true);
    setError(null);
    const body: EtfPortfolioBuildBody = {
      target_symbol: targetSymbol,
      lookback_days: lookbackDays,
      rebalance_frequency: rebalanceFrequency || null,
      max_weight: maxWeight,
      max_positions: maxPositions ? Number(maxPositions) : null,
      min_scale: minScale ? Number(minScale) : null,
      max_fee: maxFee ? Number(maxFee) : null,
      max_turnover: maxTurnover ? Number(maxTurnover) : null,
    };
    try {
      const res = await api.buildEtfPortfolio(body);
      if (res.data) {
        setResult(res.data);
      } else {
        setError(res.warnings.join("；") || "构建未返回数据");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  // ---- 派生数据 ----
  const memberRows: MemberRow[] = useMemo(() => {
    if (!result) return [];
    return Object.entries(result.member_weights).map(([code, m]) => ({
      fund_code: code,
      weight: m.weight,
      fund_name: m.fund_name,
      fee_pct: m.fee_pct,
      scale: m.scale,
      avg_daily_amount: m.avg_daily_amount,
      tracking_error_1y: m.tracking_error_1y,
    }));
  }, [result]);

  const fitted = result?.portfolio_stats?.fitted ?? {};
  const summary = result?.backtest?.summary;
  const rebalances = result?.backtest?.rebalances ?? [];
  const industryRows = result?.industry_deviation?.rows ?? [];

  const fitCurveOption = useMemo(() => {
    const curve = result?.backtest?.fit_curve ?? [];
    if (curve.length === 0) return null;
    return {
      title: { text: "历史拟合曲线（组合 vs 目标指数）", left: 0 },
      tooltip: { trigger: "axis" as const },
      legend: { top: 0, right: 0 },
      grid: { left: 48, right: 16, top: 40, bottom: 28 },
      xAxis: { type: "time" as const },
      yAxis: { type: "value" as const, scale: true },
      series: [
        {
          name: "组合",
          type: "line" as const,
          showSymbol: false,
          data: curve.map((p) => [p.date, p.portfolio]),
        },
        {
          name: result?.target_name ?? result?.target_symbol ?? "目标指数",
          type: "line" as const,
          showSymbol: false,
          data: curve.map((p) => [p.date, p.index]),
        },
      ],
    };
  }, [result]);

  const memberColumns: Column<MemberRow>[] = [
    {
      key: "fund",
      header: "基金",
      render: (m) => (
        <div>
          <div>{m.fund_name ?? m.fund_code}</div>
          <div className="mono text-tertiary text-xs">{m.fund_code}</div>
        </div>
      ),
    },
    {
      key: "weight",
      header: "推荐权重",
      numeric: true,
      sortable: true,
      sortValue: (m) => m.weight,
      render: (m) => <strong>{fmtPct(m.weight, 2)}</strong>,
    },
    {
      key: "fee",
      header: "综合费率",
      numeric: true,
      render: (m) => (m.fee_pct != null ? `${m.fee_pct.toFixed(2)}%` : "—"),
    },
    {
      key: "scale",
      header: "规模（亿）",
      numeric: true,
      sortValue: (m) => m.scale,
      sortable: true,
      render: (m) => (m.scale != null ? m.scale.toFixed(1) : "—"),
    },
    {
      key: "liquidity",
      header: "日均成交额",
      numeric: true,
      sortValue: (m) => m.avg_daily_amount,
      sortable: true,
      render: (m) =>
        m.avg_daily_amount != null ? `${(m.avg_daily_amount / 1e8).toFixed(2)} 亿` : "—",
    },
    {
      key: "te",
      header: "跟踪误差(1Y)",
      numeric: true,
      render: (m) => fmtPct(m.tracking_error_1y),
    },
  ];

  const rebalanceColumns: Column<(typeof rebalances)[number]>[] = [
    { key: "date", header: "再平衡日", render: (r) => <span className="mono">{r.date}</span> },
    {
      key: "turnover",
      header: "单边换手",
      numeric: true,
      sortValue: (r) => r.turnover,
      sortable: true,
      render: (r) => (r.skipped ? "—" : fmtPct(r.turnover, 2)),
    },
    {
      key: "cost",
      header: "成本（费率×换手）",
      numeric: true,
      render: (r) => (r.skipped ? "—" : fmtPct(r.cost, 4)),
    },
    {
      key: "cap",
      header: "换手上限",
      render: (r) =>
        r.skipped ? (
          <span className="text-tertiary" title={r.reason}>跳过</span>
        ) : r.turnover_cap_satisfied ? (
          "满足"
        ) : (
          <span style={{ color: "var(--color-danger, #c00)" }}>超限</span>
        ),
    },
    {
      key: "weights",
      header: "权重快照",
      render: (r) =>
        r.weights
          ? Object.entries(r.weights)
              .map(([c, w]) => `${c}:${(w * 100).toFixed(1)}%`)
              .join(" ")
          : r.reason ?? "—",
    },
  ];

  const constraintColumns: Column<EtfPortfolioConstraint>[] = [
    { key: "name", header: "约束", render: (c) => c.name },
    {
      key: "value",
      header: "参数值",
      render: (c) => <span className="mono">{String(c.value)}</span>,
    },
    {
      key: "satisfied",
      header: "状态",
      render: (c) =>
        c.satisfied ? (
          <span style={{ color: "var(--color-success, #2a7)" }}>满足</span>
        ) : (
          <span style={{ color: "var(--color-danger, #c00)" }}>未满足</span>
        ),
    },
    {
      key: "detail",
      header: "明细",
      render: (c) => <span className="text-tertiary">{c.detail}</span>,
    },
  ];

  const industryColumns: Column<(typeof industryRows)[number]>[] = [
    { key: "industry", header: "申万行业", render: (r) => r.industry },
    {
      key: "portfolio_weight",
      header: "组合权重",
      numeric: true,
      render: (r) => fmtPct(r.portfolio_weight, 2),
    },
    {
      key: "target_weight",
      header: "目标指数权重",
      numeric: true,
      render: (r) => fmtPct(r.target_weight, 2),
    },
    {
      key: "deviation",
      header: "偏离",
      numeric: true,
      sortValue: (r) => Math.abs(r.deviation),
      sortable: true,
      render: (r) => (
        <span style={{ color: Math.abs(r.deviation) > 0.02 ? "var(--color-danger, #c00)" : undefined }}>
          {fmtPct(r.deviation, 2)}
        </span>
      ),
    },
  ];

  const teAcceptance = useMemo(() => {
    const te = fitted.annualized_tracking_error;
    const worst = fitted.worst_single_tracking_error;
    if (te == null || worst == null) return null;
    return te < worst;
  }, [fitted]);

  return (
    <div className="page">
      <Breadcrumb items={BREADCRUMB} />
      <SectionHeader
        title="ETF 组合构建"
        subtitle="CVXPY 二次规划最小化跟踪误差（Ledoit-Wolf 收缩协方差），约束逐条可回显；月度/季度再平衡回测输出换手与成本"
      />

      {/* 参数表单 */}
      <div
        className="grid gap-4"
        style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))", marginBottom: 16 }}
      >
        <label className="text-xs text-tertiary">
          目标指数
          <select
            className="input"
            value={targetSymbol}
            onChange={(e) => setTargetSymbol(e.target.value)}
          >
            {TARGET_OPTIONS.map((o) => (
              <option key={o.symbol} value={o.symbol}>
                {o.label}（{o.symbol}）
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-tertiary">
          估计窗口（交易日）
          <input
            className="input"
            type="number"
            min={60}
            max={1500}
            value={lookbackDays}
            onChange={(e) => setLookbackDays(Number(e.target.value) || 252)}
          />
        </label>
        <label className="text-xs text-tertiary">
          再平衡频率
          <select
            className="input"
            value={rebalanceFrequency}
            onChange={(e) => setRebalanceFrequency(e.target.value)}
          >
            <option value="monthly">月度</option>
            <option value="quarterly">季度</option>
          </select>
        </label>
        <label className="text-xs text-tertiary">
          单只权重上限
          <input
            className="input"
            type="number"
            min={0.05}
            max={1}
            step={0.05}
            value={maxWeight}
            onChange={(e) => setMaxWeight(Number(e.target.value) || 1)}
          />
        </label>
        <label className="text-xs text-tertiary">
          持仓数量上限（可空）
          <input
            className="input"
            type="number"
            min={1}
            value={maxPositions}
            onChange={(e) => setMaxPositions(e.target.value)}
          />
        </label>
        <label className="text-xs text-tertiary">
          规模下限（亿元，可空）
          <input
            className="input"
            type="number"
            min={0}
            value={minScale}
            onChange={(e) => setMinScale(e.target.value)}
          />
        </label>
        <label className="text-xs text-tertiary">
          费率上限（%/年，可空）
          <input
            className="input"
            type="number"
            min={0}
            step={0.1}
            value={maxFee}
            onChange={(e) => setMaxFee(e.target.value)}
          />
        </label>
        <label className="text-xs text-tertiary">
          换手上限（双边，可空）
          <input
            className="input"
            type="number"
            min={0}
            max={2}
            step={0.05}
            value={maxTurnover}
            onChange={(e) => setMaxTurnover(e.target.value)}
          />
        </label>
      </div>

      <div style={{ marginBottom: 20 }}>
        <button className="btn btn-primary" onClick={handleBuild} disabled={running}>
          {running ? "构建中…" : "构建 ETF 组合"}
        </button>
        <span className="text-tertiary text-xs" style={{ marginLeft: 12 }}>
          默认候选池为样本内 ETF/联接，跟踪目标指数的产品自动归组
        </span>
      </div>

      {error && <ErrorState title="构建失败" desc={error} />}
      {loading && <LoadingState rows={5} cols={6} />}

      {!loading && !error && !result && (
        <EmptyState
          title="暂无构建记录"
          desc="设置参数后点击「构建 ETF 组合」：二次规划求解推荐权重，并执行再平衡回测"
        />
      )}

      {!loading && result && (
        <>
          <div className="grid grid-cols-4 gap-4" style={{ marginBottom: 16 }}>
            <MetricCard
              label="目标指数"
              value={result.target_name ?? result.target_symbol}
              sub={`候选 ${result.candidate_count} → 入选 ${result.eligible_count} 只`}
            />
            <MetricCard
              label="拟合跟踪误差（年化）"
              value={fmtPct(fitted.annualized_tracking_error)}
              sub={
                fitted.worst_single_tracking_error != null
                  ? `单只最差候选 ${fmtPct(fitted.worst_single_tracking_error)}${
                      teAcceptance === true ? "（组合更优 ✓）" : teAcceptance === false ? "（组合未跑赢）" : ""
                    }`
                  : undefined
              }
            />
            <MetricCard
              label="组合费率 / 规模"
              value={`${fmtNum(result.portfolio_stats?.weighted_fee_pct)}%`}
              sub={`加权规模 ${fmtNum(result.portfolio_stats?.weighted_scale, 1)} 亿`}
            />
            <MetricCard
              label="样本外回测换手 / 成本"
              value={summary ? `${fmtPct(summary.total_turnover as number | undefined, 1)}` : "—"}
              sub={summary ? `累计成本 ${fmtPct(summary.total_cost as number | undefined, 3)}` : result.backtest?.reason}
            />
          </div>

          <div style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 12 }}>
            <StatusBadge status={result.conclusion_status} />
            <span className="text-tertiary text-xs">
              估计窗口 {result.window_start ?? "—"} → {result.window_end ?? "—"}
              ；算法版本 {result.algorithm_version ?? "—"}
              {result.id != null ? `；记录 #${result.id}` : "；干跑未落库"}
            </span>
          </div>
          {result.warnings.length > 0 && (
            <div className="text-tertiary text-xs" style={{ marginBottom: 12 }}>
              {result.warnings.join("；")}
            </div>
          )}

          {memberRows.length > 0 ? (
            <>
              <SectionHeader title="推荐权重" subtitle="约束满足前提下的跟踪误差最小化权重" />
              <DataTable
                columns={memberColumns}
                data={memberRows}
                rowKey={(m) => m.fund_code}
                onRowClick={(m) => navigate(`/funds/${m.fund_code}`)}
                initialSort={{ key: "weight", order: "desc" }}
              />
            </>
          ) : (
            <EmptyState title="未输出推荐权重" desc="候选池不足或序列过短，结论已降级" />
          )}

          {/* 约束逐条回显 */}
          {result.constraints.length > 0 && (
            <>
              <SectionHeader title="约束回显" subtitle="每条约束的参数值、是否满足与实际值（§7.3 可解释性）" />
              <DataTable
                columns={constraintColumns}
                data={result.constraints}
                rowKey={(c) => c.name}
              />
            </>
          )}

          {/* 拟合曲线 */}
          {fitCurveOption && (
            <div style={{ marginBottom: 16 }}>
              <ChartWrapper option={fitCurveOption} height={300} />
              <div className="text-tertiary text-xs" style={{ marginTop: 6 }}>
                近一年窗口组合净值 vs 目标指数（历史拟合，非预测）
              </div>
            </div>
          )}

          {/* 再平衡回测 */}
          {result.backtest?.available && rebalances.length > 0 && (
            <>
              <SectionHeader
                title="再平衡回测"
                subtitle={`样本外 ${fmtNum(summary?.observations as number | undefined, 0)} 交易日；${summary?.rebalance_frequency} 再平衡 ${summary?.rebalance_count} 次；样本外跟踪误差 ${fmtPct(summary?.annualized_tracking_error as number | undefined)}`}
              />
              <DataTable
                columns={rebalanceColumns}
                data={rebalances}
                rowKey={(r) => r.date}
              />
            </>
          )}

          {/* 行业偏离 */}
          <SectionHeader
            title="行业偏离对照"
            subtitle="组合行业权重（按成员跟踪指数的申万行业权重合成）vs 目标指数"
          />
          {result.industry_deviation?.available && industryRows.length > 0 ? (
            <>
              <div className="text-tertiary text-xs" style={{ marginBottom: 8 }}>
                绝对偏离合计 {fmtPct(result.industry_deviation.total_abs_deviation)}
                {result.industry_deviation.uncovered?.length
                  ? `；未覆盖成员：${result.industry_deviation.uncovered.join("、")}`
                  : ""}
              </div>
              <DataTable
                columns={industryColumns}
                data={industryRows}
                rowKey={(r) => r.industry}
                initialSort={{ key: "deviation", order: "desc" }}
              />
            </>
          ) : (
            <EmptyState
              title="行业偏离不可得"
              desc={result.industry_deviation?.reason ?? "无行业权重对照数据"}
            />
          )}
        </>
      )}
    </div>
  );
}
