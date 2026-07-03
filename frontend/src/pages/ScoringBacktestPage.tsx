// 评分回测 — IC/IR 指标卡 + 分组柱状图 + 分组指标表
// 创建回测 / 列表 / 详情 Drawer

import { useEffect, useState } from "react";
import { api, type ScoringBacktestItem, type ScoringBacktestDetail } from "../api/client";
import {
  SectionHeader,
  StatusBadge,
  Breadcrumb,
  MetricCard,
  LoadingState,
  EmptyState,
  Drawer,
  type BreadcrumbItem,
} from "../components/display";
import { DataTable, type Column } from "../components/data/DataTable";
import { ChartWrapper } from "../components/data/ChartWrapper";
import type { EChartsOption } from "echarts";

const PRESET_OPTIONS = ["均衡型", "稳健型", "进取型"];
const METRIC_LABELS: Record<string, string> = {
  future_return: "未来收益",
  future_max_drawdown: "最大回撤",
  future_sharpe: "夏普",
};

const GROUP_LABELS = ["Q1", "Q2", "Q3", "Q4", "Q5"];

export default function ScoringBacktestPage() {
  const [backtests, setBacktests] = useState<ScoringBacktestItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [fundCodes, setFundCodes] = useState("000001");
  const [backtestStart, setBacktestStart] = useState("2022-01-01");
  const [backtestEnd, setBacktestEnd] = useState("2025-12-31");
  const [preset, setPreset] = useState("均衡型");
  const [creating, setCreating] = useState(false);

  // Detail
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ScoringBacktestDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const body = await api.listScoringBacktests();
      if (body.data === null) {
        setErrorMessage(body.warnings.join("; ") || "加载失败");
        return;
      }
      setBacktests(body.data.backtests ?? []);
    } catch (e) {
      setErrorMessage(`加载异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function loadDetail(id: number) {
    setSelectedId(id);
    setDetailLoading(true);
    try {
      const body = await api.getScoringBacktest(id);
      if (body.data === null) {
        setErrorMessage(body.warnings.join("; ") || "加载详情失败");
        return;
      }
      setDetail(body.data as ScoringBacktestDetail | null);
    } catch (e) {
      setErrorMessage(`加载详情异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDetailLoading(false);
    }
  }

  async function create() {
    setCreating(true);
    try {
      const body = await api.runScoringBacktest({
        fund_codes: fundCodes.split(",").map((s) => s.trim()).filter(Boolean),
        backtest_start: backtestStart,
        backtest_end: backtestEnd,
        preset,
        forward_months: 12,
        min_forward_observations: 60,
      });
      if (body.data === null) {
        setErrorMessage(`回测失败: ${body.warnings.join("; ") || "未知错误"}`);
        return;
      }
      setErrorMessage(null);
      setShowCreate(false);
      load();
    } catch (e) {
      setErrorMessage(`回测异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCreating(false);
    }
  }

  const crumbs: BreadcrumbItem[] = [
    { label: "算法实验" },
    { label: "评分回测" },
  ];

  const columns: Column<ScoringBacktestItem>[] = [
    {
      key: "id",
      header: "ID",
      sortable: true,
      sortValue: (r) => r.id,
      render: (r) => <span className="mono">{r.id}</span>,
      width: "60px",
    },
    {
      key: "score_version",
      header: "版本",
      sortable: true,
      sortValue: (r) => r.score_version,
      render: (r) => <span className="mono">{r.score_version}</span>,
    },
    {
      key: "backtest_date",
      header: "日期",
      sortable: true,
      sortValue: (r) => r.backtest_date ?? "",
      render: (r) => r.backtest_date ?? "—",
    },
    {
      key: "group_count",
      header: "分组数",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.group_count,
    },
    {
      key: "ic_mean",
      header: "IC Mean",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.ic_mean,
      render: (r) => (
        <span className="mono">
          {r.ic_mean != null ? r.ic_mean.toFixed(4) : "—"}
        </span>
      ),
    },
    {
      key: "ic_ir",
      header: "IC IR",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.ic_ir,
      render: (r) => (
        <span className="mono">
          {r.ic_ir != null ? r.ic_ir.toFixed(4) : "—"}
        </span>
      ),
    },
    {
      key: "monotonicity_check",
      header: "单调性",
      sortable: true,
      sortValue: (r) => (r.monotonicity_check ? 1 : 0),
      render: (r) => (
        <StatusBadge
          status={
            r.monotonicity_check === true
              ? "computed"
              : r.monotonicity_check === false
                ? "needs_review"
                : "observation"
          }
        />
      ),
    },
    {
      key: "created_at",
      header: "创建时间",
      sortable: true,
      sortValue: (r) => r.created_at ?? "",
      render: (r) => (
        <span className="mono text-sm">{r.created_at?.slice(0, 10) ?? "—"}</span>
      ),
    },
  ];

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center justify-between">
          <h1>评分回测</h1>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => setShowCreate(!showCreate)}
          >
            {showCreate ? "收起" : "+ 新建回测"}
          </button>
        </div>
        <div className="text-sm text-tertiary mt-2">
          {backtests.length} 次回测 · 验证评分对未来收益的预测能力
        </div>
      </div>

      {/* 错误提示 */}
      {errorMessage && (
        <div
          className="fade-up fade-up-2 mb-4"
          style={{
            padding: "var(--space-3) var(--space-4)",
            background: "var(--negative-soft)",
            borderLeft: "3px solid var(--negative)",
            borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
          }}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm" style={{ color: "var(--negative)" }}>
              {errorMessage}
            </span>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setErrorMessage(null)}
            >
              关闭
            </button>
          </div>
        </div>
      )}

      {/* 创建回测表单 */}
      {showCreate && (
        <div
          className="fade-up fade-up-2 mb-4"
          style={{
            background: "var(--surface-raised)",
            borderRadius: "var(--radius-md)",
            padding: "var(--space-4)",
            border: "1px solid var(--border-hairline)",
          }}
        >
          <SectionHeader title="新建回测" subtitle="配置基金样本和回测区间" />
          <div
            className="grid mt-3"
            style={{
              gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
              gap: "var(--space-3)",
            }}
          >
            <label className="form-label">
              <span>基金代码</span>
              <input
                className="form-input"
                value={fundCodes}
                onChange={(e) => setFundCodes(e.target.value)}
                placeholder="000001,163406"
              />
            </label>
            <label className="form-label">
              <span>回测起点</span>
              <input
                className="form-input"
                type="date"
                value={backtestStart}
                onChange={(e) => setBacktestStart(e.target.value)}
              />
            </label>
            <label className="form-label">
              <span>回测终点</span>
              <input
                className="form-input"
                type="date"
                value={backtestEnd}
                onChange={(e) => setBacktestEnd(e.target.value)}
              />
            </label>
            <label className="form-label">
              <span>评分预设</span>
              <select
                className="form-input"
                value={preset}
                onChange={(e) => setPreset(e.target.value)}
              >
                {PRESET_OPTIONS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="mt-3">
            <button
              className="btn btn-primary"
              onClick={create}
              disabled={creating}
            >
              {creating ? "运行中..." : "运行回测"}
            </button>
          </div>
        </div>
      )}

      {/* 回测列表 */}
      <div className="fade-up fade-up-3">
        {loading ? (
          <LoadingState rows={6} cols={6} />
        ) : backtests.length === 0 ? (
          <EmptyState
            title="暂无回测记录"
            desc="创建一次回测来验证评分的预测能力"
          />
        ) : (
          <div
            style={{
              background: "var(--surface-raised)",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--border-hairline)",
              overflow: "hidden",
            }}
          >
            <DataTable
              columns={columns}
              data={backtests}
              rowKey={(r) => String(r.id)}
              onRowClick={(r) => loadDetail(r.id)}
              initialSort={{ key: "created_at", order: "desc" }}
            />
          </div>
        )}
      </div>

      {/* 详情 Drawer */}
      <Drawer
        open={selectedId !== null}
        onClose={() => {
          setSelectedId(null);
          setDetail(null);
        }}
        title={`回测详情 #${selectedId ?? ""}`}
      >
        {detailLoading ? (
          <LoadingState rows={5} cols={3} />
        ) : detail ? (
          <BacktestDetailContent detail={detail} />
        ) : (
          <EmptyState title="加载失败" />
        )}
      </Drawer>
    </div>
  );
}

// ---- 回测详情内容 ----

function BacktestDetailContent({ detail }: { detail: ScoringBacktestDetail }) {
  const groupResults = detail.group_results ?? {};
  const hasGroupResults = Object.keys(groupResults).length > 0;

  // 分组收益柱状图
  const returnChartOption: EChartsOption | null =
    groupResults.future_return
      ? {
          title: { text: "分组未来收益（Q1=最低分, Q5=最高分）" },
          tooltip: {
            trigger: "axis",
            formatter: (params: unknown) => {
              const p = (params as Array<{ name: string; value: number }>)[0];
              return `${p.name}: ${(p.value * 100).toFixed(2)}%`;
            },
          },
          xAxis: {
            type: "category",
            data: GROUP_LABELS.slice(0, Object.keys(groupResults.future_return).length),
          },
          yAxis: {
            type: "value",
            name: "收益率",
            axisLabel: {
              formatter: (v: number) => `${(v * 100).toFixed(1)}%`,
            },
          },
          series: [
            {
              type: "bar",
              data: ["0", "1", "2", "3", "4"]
                .map((g) => groupResults.future_return![g])
                .filter((v) => v != null),
              itemStyle: { color: "#B45309" },
              barWidth: "50%",
            },
          ],
        }
      : null;

  // 分组夏普柱状图
  const sharpeChartOption: EChartsOption | null =
    groupResults.future_sharpe
      ? {
          title: { text: "分组未来夏普比率" },
          tooltip: { trigger: "axis" },
          xAxis: {
            type: "category",
            data: GROUP_LABELS.slice(0, Object.keys(groupResults.future_sharpe).length),
          },
          yAxis: {
            type: "value",
            name: "Sharpe",
            axisLabel: { formatter: (v: number) => v.toFixed(2) },
          },
          series: [
            {
              type: "bar",
              data: ["0", "1", "2", "3", "4"]
                .map((g) => groupResults.future_sharpe![g])
                .filter((v) => v != null),
              itemStyle: { color: "#3B6EA5" },
              barWidth: "50%",
            },
          ],
        }
      : null;

  return (
    <div>
      {/* 核心指标卡 */}
      <div className="grid grid-4 mb-4">
        <MetricCard
          label="IC Mean"
          value={detail.ic_mean != null ? detail.ic_mean.toFixed(4) : "—"}
          sub={
            detail.ic_mean != null && detail.ic_mean > 0
              ? "正向预测力"
              : "无预测力或反向"
          }
          positive={detail.ic_mean != null && detail.ic_mean > 0}
          negative={detail.ic_mean != null && detail.ic_mean <= 0}
        />
        <MetricCard
          label="IC IR"
          value={detail.ic_ir != null ? detail.ic_ir.toFixed(4) : "—"}
          sub={
            detail.ic_ir != null && detail.ic_ir > 0.5
              ? "稳定性良好"
              : "稳定性不足"
          }
          positive={detail.ic_ir != null && detail.ic_ir > 0.5}
        />
        <MetricCard
          label="单调性"
          value={
            detail.monotonicity_check === true
              ? "通过"
              : detail.monotonicity_check === false
                ? "未通过"
                : "—"
          }
          positive={detail.monotonicity_check === true}
          negative={detail.monotonicity_check === false}
        />
        <MetricCard
          label="评估期数"
          value={detail.group_count}
          sub="分组数量"
        />
      </div>

      {/* 分组指标表 */}
      {hasGroupResults && (
        <div className="mb-4">
          <SectionHeader title="分组指标" subtitle="各分组的未来表现" />
          <div
            className="mt-3"
            style={{
              background: "var(--surface-base)",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border-hairline)",
              overflow: "auto",
            }}
          >
            <table className="data-table">
              <thead>
                <tr>
                  <th>指标</th>
                  {GROUP_LABELS.map((g) => (
                    <th key={g} className="numeric">
                      {g}
                    </th>
                  ))}
                  <th>单调性</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(groupResults).map(([metric, groups]) => (
                  <tr key={metric}>
                    <td>{METRIC_LABELS[metric] ?? metric}</td>
                    {["0", "1", "2", "3", "4"].map((group) => {
                      const value = groups[group];
                      return (
                        <td key={group} className="mono numeric">
                          {value == null
                            ? "—"
                            : metric === "future_sharpe"
                              ? value.toFixed(2)
                              : `${(value * 100).toFixed(2)}%`}
                        </td>
                      );
                    })}
                    <td>
                      <StatusBadge
                        status={
                          detail.detail?.monotonicity_checks?.[metric]
                            ? "computed"
                            : "needs_review"
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 分组收益柱状图 */}
      {returnChartOption && (
        <div className="mb-4">
          <ChartWrapper option={returnChartOption} height={280} />
        </div>
      )}

      {/* 分组夏普柱状图 */}
      {sharpeChartOption && (
        <div className="mb-4">
          <ChartWrapper option={sharpeChartOption} height={240} />
        </div>
      )}

      {/* 元数据 */}
      {detail.detail && (
        <div>
          <SectionHeader title="元数据" />
          <div
            className="mt-3"
            style={{
              padding: "var(--space-3) var(--space-4)",
              background: "var(--surface-sunken)",
              borderRadius: "var(--radius-sm)",
              fontSize: "0.82rem",
            }}
          >
            <div className="flex items-center justify-between" style={{ padding: "var(--space-1) 0" }}>
              <span className="text-tertiary">IC 期数</span>
              <span className="mono">{String(detail.detail.ic_count ?? "—")}</span>
            </div>
            <div className="flex items-center justify-between" style={{ padding: "var(--space-1) 0" }}>
              <span className="text-tertiary">前瞻月份</span>
              <span className="mono">{String(detail.detail.forward_months ?? "—")}</span>
            </div>
            <div className="flex items-center justify-between" style={{ padding: "var(--space-1) 0" }}>
              <span className="text-tertiary">评估日期数</span>
              <span className="mono">{String(detail.detail.eval_date_count ?? "—")}</span>
            </div>
            {Array.isArray(detail.detail.warnings) &&
              detail.detail.warnings.length > 0 && (
                <div className="mt-2 flex flex-col gap-1">
                  {detail.detail.warnings.map((w, i) => (
                    <div key={i} className="text-xs text-warning">
                      {"⚠ " + String(w)}
                    </div>
                  ))}
                </div>
              )}
          </div>
        </div>
      )}
    </div>
  );
}
