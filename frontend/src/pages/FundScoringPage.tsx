// 基金综合评分 — 指标卡 + 维度子评分柱状图 + 评分排名表
// 支持从基金详情跳转自动评分，或手动输入基金代码运行评分

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type FundScoreItem } from "../api/client";
import {
  SectionHeader,
  StatusBadge,
  Breadcrumb,
  MetricCard,
  LoadingState,
  EmptyState,
  type BreadcrumbItem,
} from "../components/display";
import { DataTable, type Column } from "../components/data/DataTable";
import { ChartWrapper } from "../components/data/ChartWrapper";
import type { EChartsOption } from "echarts";

const DIM_LABELS: Record<string, string> = {
  return: "收益能力",
  risk: "风险控制",
  alpha: "Alpha 能力",
  trading: "交易能力",
  style_stability: "风格稳定性",
  scale: "规模适配",
  team: "团队稳定性",
  holder: "持有人稳定性",
};

const PRESET_OPTIONS = ["均衡型", "稳健型", "进取型"];

type RankedScore = FundScoreItem & { rank: number };

export default function FundScoringPage() {
  const { code } = useParams<{ code: string }>();
  const [scores, setScores] = useState<FundScoreItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [scoreVersion, setScoreVersion] = useState<string | null>(null);

  // Run scoring form
  const [fundCodes, setFundCodes] = useState(code || "");
  const [preset, setPreset] = useState("均衡型");
  const [running, setRunning] = useState(false);

  // If navigated from fund detail, auto-run scoring for that fund
  useEffect(() => {
    if (code) {
      setFundCodes(code);
      runScoring(code);
    }
  }, [code]);

  async function runScoring(codes?: string) {
    const codesStr = (codes || fundCodes).trim();
    if (!codesStr) return;

    setRunning(true);
    setErrorMessage(null);
    try {
      const body = await api.runScoring({
        fund_codes: codesStr.split(",").map((s) => s.trim()).filter(Boolean),
        preset,
      });
      if (body.data === null) {
        setErrorMessage(body.warnings.join("; ") || "评分失败");
        return;
      }
      setScores(body.data.fund_scores ?? []);
      setScoreVersion(body.data.score_version);
    } catch (e) {
      setErrorMessage(`评分异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRunning(false);
      setLoading(false);
    }
  }

  // Load latest score for this fund on initial mount
  useEffect(() => {
    if (!code) {
      setLoading(false);
      return;
    }
    // auto-run handles loading
  }, []);

  const fundScore = scores.find((s) => s.fund_code === code) || scores[0];

  const crumbs: BreadcrumbItem[] = code
    ? [{ label: "基金筛选" }, { label: code }, { label: "综合评分" }]
    : [{ label: "基金筛选" }, { label: "综合评分" }];

  // 按总分降序预排序，赋予排名（排名为基金固有属性，不随表格排序变化）
  const rankedScores: RankedScore[] = [...scores]
    .sort((a, b) => b.total_score - a.total_score)
    .map((s, i) => ({ ...s, rank: i + 1 }));

  // 维度子评分柱状图（按分数降序排列维度）
  const sortedEntries = fundScore
    ? Object.entries(fundScore.sub_scores).sort(([, a], [, b]) => b - a)
    : [];
  const subScoreOption: EChartsOption = {
    title: { text: "维度子评分" },
    tooltip: { trigger: "axis" },
    xAxis: {
      type: "category",
      data: sortedEntries.map(([dim]) => DIM_LABELS[dim] || dim),
    },
    yAxis: { type: "value", name: "评分" },
    series: [
      {
        type: "bar",
        data: sortedEntries.map(([, score]) => score),
        itemStyle: { color: "#B45309" },
        barWidth: "50%",
      },
    ],
  };

  const rankingColumns: Column<RankedScore>[] = [
    {
      key: "rank",
      header: "排名",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.rank,
      render: (r) => <span className="mono">{r.rank}</span>,
      width: "70px",
    },
    {
      key: "fund_code",
      header: "基金代码",
      sortable: true,
      sortValue: (r) => r.fund_code,
      render: (r) => (
        <span className={`mono ${r.fund_code === code ? "font-medium" : ""}`}>
          {r.fund_code}
          {r.fund_code === code && (
            <span className="text-tertiary text-xs ml-1">· 当前</span>
          )}
        </span>
      ),
    },
    {
      key: "total_score",
      header: "总分",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.total_score,
      render: (r) => (
        <span className="mono font-medium">{r.total_score.toFixed(1)}</span>
      ),
    },
    {
      key: "percentile_rank",
      header: "分位数",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.percentile_rank,
      render: (r) => (
        <span className="mono">前 {(r.percentile_rank * 100).toFixed(0)}%</span>
      ),
    },
    {
      key: "contains_estimated",
      header: "含估计",
      sortable: true,
      sortValue: (r) => (r.contains_estimated ? 1 : 0),
      render: (r) => (
        <StatusBadge status={r.contains_estimated ? "estimated" : "computed"} />
      ),
    },
    {
      key: "deduction_reasons",
      header: "扣分项",
      render: (r) =>
        r.deduction_reasons.length > 0 ? (
          <span className="text-sm text-secondary">
            {r.deduction_reasons.join("; ")}
          </span>
        ) : (
          <span className="text-tertiary">—</span>
        ),
    },
  ];

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center justify-between">
          <h1>综合评分</h1>
          {scoreVersion && (
            <span className="text-sm text-tertiary mono">
              版本 {scoreVersion} · {scores.length} 只基金
            </span>
          )}
        </div>
        <div className="text-sm text-tertiary mt-2">
          基于多维度的基金综合评分与同类排名
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

      {/* 运行评分表单 — 未指定 code 或暂无结果时显示 */}
      {(!code || (!loading && !fundScore)) && (
        <div
          className="fade-up fade-up-2 mb-4"
          style={{
            background: "var(--surface-raised)",
            borderRadius: "var(--radius-md)",
            padding: "var(--space-4)",
            border: "1px solid var(--border-hairline)",
          }}
        >
          <SectionHeader title="运行评分" subtitle="输入基金代码并选择评分预设" />
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
              onClick={() => runScoring()}
              disabled={running}
            >
              {running ? "评分中..." : "运行评分"}
            </button>
          </div>
        </div>
      )}

      {/* 主体内容 */}
      {loading ? (
        <div className="fade-up fade-up-3">
          <LoadingState rows={5} cols={4} />
        </div>
      ) : !fundScore ? (
        <div className="fade-up fade-up-3">
          <EmptyState
            title={code ? `基金 ${code} 暂无评分数据` : "暂无评分结果"}
            desc="输入基金代码并点击「运行评分」生成评分"
          />
        </div>
      ) : (
        <div>
          {/* 汇总指标卡 */}
          <div className="grid grid-4 fade-up fade-up-3 mb-4">
            <MetricCard
              label="综合评分"
              value={`${fundScore.total_score.toFixed(1)} / 100`}
              sub={fundScore.contains_estimated ? "含估计成分" : "全量计算"}
            />
            <MetricCard
              label="同类排名"
              value={`前 ${(fundScore.percentile_rank * 100).toFixed(0)}%`}
            />
            <MetricCard
              label="评分版本"
              value={scoreVersion || "—"}
            />
            <MetricCard
              label="扣分项"
              value={`${fundScore.deduction_reasons.length} 项`}
              sub={
                fundScore.deduction_reasons.length > 0
                  ? fundScore.deduction_reasons.join("; ")
                  : "无扣分"
              }
              negative={fundScore.deduction_reasons.length > 0}
            />
          </div>

          {/* 维度子评分柱状图 */}
          <div
            className="fade-up fade-up-4 mb-4"
            style={{
              background: "var(--surface-raised)",
              borderRadius: "var(--radius-md)",
              padding: "var(--space-4)",
              border: "1px solid var(--border-hairline)",
            }}
          >
            <ChartWrapper option={subScoreOption} height={280} />
          </div>

          {/* 评分排名表 */}
          {scores.length > 1 && (
            <div className="fade-up fade-up-5">
              <SectionHeader title="评分排名" subtitle="按总分降序排列" />
              <div
                className="mt-3"
                style={{
                  background: "var(--surface-raised)",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--border-hairline)",
                  overflow: "hidden",
                }}
              >
                <DataTable
                  columns={rankingColumns}
                  data={rankedScores}
                  rowKey={(r) => r.fund_code}
                  initialSort={{ key: "rank", order: "asc" }}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
