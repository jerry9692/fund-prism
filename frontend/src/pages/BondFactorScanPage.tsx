// 债基风险扫描（P4B，需求书 §6.2.7）
// 债基四模板滚动回归 → 因子暴露曲线 + 久期/信用/票息杠杆/转债/权益雷达 + 回归稳定性（滚动 R²）
// 回归暴露为模型估计（estimated_*），结论状态按门禁与覆盖度分级

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type BondFactorExposureItem } from "../api/client";
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

const TEMPLATE_LABELS: Record<string, string> = {
  bond_pure: "纯债",
  bond_short: "短债",
  bond_secondary: "二级债基",
  bond_convertible: "转债基金",
};

const RADAR_AXES: Array<{ key: keyof BondFactorExposureItem["radar"]; label: string }> = [
  { key: "duration", label: "久期（隐含）" },
  { key: "credit", label: "信用" },
  { key: "coupon_carry_annualized", label: "票息/杠杆" },
  { key: "convertible", label: "转债" },
  { key: "equity_beta", label: "权益 Beta" },
];

const BREADCRUMB: BreadcrumbItem[] = [{ label: "债基风险扫描" }];

function fmtNum(v: number | null | undefined, digits = 3): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export default function BondFactorScanPage() {
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [calcDate, setCalcDate] = useState<string | null>(null);
  const [results, setResults] = useState<BondFactorExposureItem[]>([]);
  const [selectedCode, setSelectedCode] = useState<string>("");

  const loadScan = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getBondFactorScan();
      if (res.data) {
        setResults(res.data.results);
        setCalcDate(res.data.calc_date);
      } else {
        setResults([]);
        setCalcDate(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadScan();
  }, [loadScan]);

  async function handleRun() {
    setRunning(true);
    setError(null);
    try {
      const res = await api.runBondFactorScan();
      if (!res.data) {
        setError(res.warnings.join("；") || "风险扫描未返回数据");
      }
      await loadScan();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  const selected = useMemo(
    () => results.find((r) => r.fund_code === selectedCode) ?? null,
    [results, selectedCode]
  );

  const statusSummary = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of results) counts[r.conclusion_status] = (counts[r.conclusion_status] ?? 0) + 1;
    return counts;
  }, [results]);

  // ---- 列表 ----
  const columns: Column<BondFactorExposureItem>[] = [
    {
      key: "fund",
      header: "基金",
      render: (r) => (
        <div>
          <div>{r.fund_name ?? r.fund_code}</div>
          <div className="mono text-tertiary text-xs">{r.fund_code}</div>
        </div>
      ),
    },
    {
      key: "template",
      header: "模板",
      render: (r) => TEMPLATE_LABELS[r.template_name ?? ""] ?? "—",
    },
    {
      key: "duration",
      header: "隐含久期",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.radar.duration,
      render: (r) => fmtNum(r.radar.duration, 1),
    },
    {
      key: "credit",
      header: "信用暴露",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.radar.credit,
      render: (r) => fmtNum(r.radar.credit),
    },
    {
      key: "convertible",
      header: "转债暴露",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.radar.convertible,
      render: (r) => fmtNum(r.radar.convertible),
    },
    {
      key: "equity",
      header: "权益 Beta",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.radar.equity_beta,
      render: (r) => fmtNum(r.radar.equity_beta),
    },
    {
      key: "r2",
      header: "全窗口 R²",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.full_window_r_squared,
      render: (r) => fmtNum(r.full_window_r_squared, 2),
    },
    {
      key: "peer",
      header: "同类 R² 排名",
      numeric: true,
      render: (r) => r.peer_rank?.r_squared?.rank_text ?? "—",
    },
    {
      key: "window",
      header: "回归窗口",
      render: (r) =>
        r.window_start && r.window_end
          ? `${r.window_start} ~ ${r.window_end}`
          : "—",
    },
    {
      key: "status",
      header: "结论状态",
      render: (r) => <StatusBadge status={r.conclusion_status} />,
    },
    {
      key: "warnings",
      header: "告警",
      render: (r) =>
        r.warnings.length > 0 ? (
          <span className="text-tertiary text-xs" title={r.warnings.join("；")}>
            {r.warnings.length} 条
          </span>
        ) : (
          "—"
        ),
    },
  ];

  // ---- 暴露曲线（时间轴，每因子一条线）----
  const exposureCurveOption = useMemo(() => {
    if (!selected) return null;
    const factors = selected.factor_names.filter(
      (f) => (selected.exposure_curves[f] ?? []).length > 0
    );
    if (factors.length === 0) return null;
    return {
      title: { text: "滚动因子暴露曲线（窗口 120 日 / 步长 20 日）", left: 0 },
      tooltip: { trigger: "axis" as const },
      legend: { top: 0, right: 0 },
      grid: { left: 48, right: 16, top: 40, bottom: 28 },
      xAxis: { type: "time" as const },
      yAxis: { type: "value" as const },
      series: factors.map((f) => ({
        name: selected.factor_labels?.[f] ?? f,
        type: "line" as const,
        showSymbol: false,
        data: selected.exposure_curves[f].map((p) => [p.date, p.exposure]),
      })),
    };
  }, [selected]);

  // ---- 回归稳定性：滚动 R² ----
  const stabilityOption = useMemo(() => {
    if (!selected) return null;
    const first = selected.factor_names
      .map((f) => selected.exposure_curves[f])
      .find((c) => c && c.length > 0);
    if (!first || first.length === 0) return null;
    return {
      title: { text: "回归稳定性（滚动窗口 R²）", left: 0 },
      tooltip: { trigger: "axis" as const },
      grid: { left: 48, right: 16, top: 40, bottom: 28 },
      xAxis: { type: "time" as const },
      yAxis: { type: "value" as const, min: 0, max: 1 },
      series: [
        {
          name: "滚动 R²",
          type: "line" as const,
          showSymbol: false,
          areaStyle: { opacity: 0.15 },
          data: first.map((p) => [p.date, p.r_squared]),
        },
      ],
    };
  }, [selected]);

  // ---- 风险雷达：各轴取池内绝对值最大值归一化到 0-100 ----
  const radarOption = useMemo(() => {
    if (!selected) return null;
    const maxAbs: Record<string, number> = {};
    for (const axis of RADAR_AXES) {
      let m = 0;
      for (const r of results) {
        const v = r.radar[axis.key];
        if (v != null && Number.isFinite(v)) m = Math.max(m, Math.abs(v));
      }
      maxAbs[axis.key] = m;
    }
    const values = RADAR_AXES.map((axis) => {
      const v = selected.radar[axis.key];
      if (v == null || !Number.isFinite(v) || maxAbs[axis.key] <= 0) return 0;
      return Math.round((Math.abs(v) / maxAbs[axis.key]) * 100);
    });
    return {
      title: { text: "风险雷达（池内归一，符号见表）", left: 0 },
      tooltip: {},
      radar: {
        indicator: RADAR_AXES.map((axis) => ({ name: axis.label, max: 100 })),
        radius: "62%",
        center: ["50%", "56%"],
      },
      series: [
        {
          type: "radar" as const,
          data: [
            {
              value: values,
              name: selected.fund_name ?? selected.fund_code,
              areaStyle: { opacity: 0.2 },
            },
          ],
        },
      ],
    };
  }, [selected, results]);

  return (
    <div className="page">
      <Breadcrumb items={BREADCRUMB} />
      <SectionHeader
        title="债基风险扫描"
        subtitle="债基四模板滚动回归粗粒度因子暴露：久期（利率）/ 信用 / 票息杠杆 / 转债 / 权益 Beta；回归暴露为模型估计，序列不足自动降级"
        actions={
          <button className="btn btn-primary" onClick={handleRun} disabled={running}>
            {running ? "扫描中…" : "运行风险扫描"}
          </button>
        }
      />

      {error && <ErrorState title="加载失败" desc={error} />}
      {loading && <LoadingState rows={6} cols={8} />}

      {!loading && !error && results.length === 0 && (
        <EmptyState
          title="暂无扫描记录"
          desc="点击右上角「运行风险扫描」，对样本内债基按四模板执行因子滚动回归"
        />
      )}

      {!loading && !error && results.length > 0 && (
        <>
          <div className="grid grid-cols-4 gap-4" style={{ marginBottom: 16 }}>
            <MetricCard label="计算日期" value={calcDate ?? "—"} />
            <MetricCard label="债基样本" value={String(results.length)} />
            <MetricCard
              label="computed / observation"
              value={`${statusSummary["computed"] ?? 0} / ${statusSummary["observation"] ?? 0}`}
            />
            <MetricCard
              label="needs_review"
              value={String(statusSummary["needs_review"] ?? 0)}
            />
          </div>

          <DataTable
            columns={columns}
            data={results}
            rowKey={(r) => r.fund_code}
            onRowClick={(r) => setSelectedCode(r.fund_code)}
            initialSort={{ key: "r2", order: "desc" }}
          />

          <SectionHeader
            title="单基金详情"
            subtitle="点击表格行选择基金：暴露曲线 + 风险雷达 + 回归稳定性 + 贡献拆解"
          />
          {!selected && <EmptyState title="请选择一只债基查看详情" />}
          {selected && (
            <>
              {selected.warnings.length > 0 && (
                <div
                  className="text-tertiary text-xs"
                  style={{ marginBottom: 12, whiteSpace: "pre-line" }}
                >
                  {selected.warnings.join("；")}
                </div>
              )}

              <div className="grid grid-cols-5 gap-4" style={{ marginBottom: 16 }}>
                <MetricCard
                  label="隐含久期（年）"
                  value={fmtNum(selected.radar.duration, 1)}
                />
                <MetricCard label="信用暴露" value={fmtNum(selected.radar.credit)} />
                <MetricCard
                  label="票息 Carry（年化）"
                  value={fmtPct(selected.radar.coupon_carry_annualized)}
                />
                <MetricCard
                  label="转债暴露"
                  value={fmtNum(selected.radar.convertible)}
                />
                <MetricCard
                  label="权益 Beta"
                  value={fmtNum(selected.radar.equity_beta)}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  {exposureCurveOption ? (
                    <ChartWrapper option={exposureCurveOption} height={300} />
                  ) : (
                    <EmptyState title="无滚动暴露曲线" desc="回归窗口不足一个完整窗口" />
                  )}
                </div>
                <div>
                  {radarOption && <ChartWrapper option={radarOption} height={300} />}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4" style={{ marginTop: 16 }}>
                <div>
                  {stabilityOption ? (
                    <ChartWrapper option={stabilityOption} height={240} />
                  ) : (
                    <EmptyState title="无滚动 R² 序列" />
                  )}
                </div>
                <div>
                  <SectionHeader title="因子收益贡献拆解" subtitle="全窗口暴露 × 因子累计收益（含截距与残差）" />
                  <table className="data-table" style={{ width: "100%" }}>
                    <thead>
                      <tr>
                        <th>项</th>
                        <th style={{ textAlign: "right" }}>累计贡献</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(selected.contributions).map(([k, v]) => (
                        <tr key={k}>
                          <td>
                            {selected.factor_labels?.[k] ??
                              (k === "intercept" ? "截距（票息等）" : k === "residual" ? "残差" : k)}
                          </td>
                          <td style={{ textAlign: "right" }} className="mono">
                            {fmtPct(v)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="text-tertiary text-xs" style={{ marginTop: 8 }}>
                    因子序列覆盖度：
                    {Object.entries(selected.factor_coverage)
                      .map(([f, c]) => `${selected.factor_labels?.[f] ?? f} ${fmtPct(c, 0)}`)
                      .join(" · ")}
                    <button
                      className="btn btn-ghost"
                      style={{ marginLeft: 12 }}
                      onClick={() => navigate(`/funds/${selected.fund_code}`)}
                    >
                      查看基金详情 →
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
