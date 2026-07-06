// 基金对比页 — 多基金横向对比
// 输入多个基金代码（逗号分隔，最多 5 只），按维度横向对比评分、风格暴露、集中度与规模

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import {
  SectionHeader,
  Breadcrumb,
  MetricCard,
  LoadingState,
  EmptyState,
  ErrorState,
  type BreadcrumbItem,
} from "../components/display";

// ---- 类型 ----

interface FundColumn {
  fund_code: string;
  short_name: string | null;
  raw: Record<string, unknown>;
}

interface CompareCell {
  text: string;
  raw: number | null;
}

interface CompareRow {
  group: string;
  label: string;
  cells: CompareCell[];
  /** true = 越高越好；false = 越低越好；null = 不高亮 */
  higherIsBetter: boolean | null;
}

interface SimilarityMatrix {
  rowCodes: string[];
  colCodes: string[];
  values: Record<string, Record<string, number | null>>;
}

// ---- 常量 ----

const MAX_FUNDS = 6;

const STYLE_LABELS: Record<string, string> = {
  large_cap: "大盘",
  small_cap: "小盘",
  mid_cap: "中盘",
  growth: "成长",
  value: "价值",
  quality: "质量",
  momentum: "动量",
  volatility: "波动率",
  liquidity: "流动性",
  size: "规模",
  beta: "Beta",
  alpha: "Alpha",
};

// 固定对比维度
const FIXED_DIMS: {
  key: string;
  label: string;
  group: string;
  higherIsBetter: boolean | null;
  fmt: "score" | "pct" | "num2";
}[] = [
  { key: "total_score", label: "综合评分", group: "评分", higherIsBetter: true, fmt: "score" },
  { key: "return_score", label: "收益评分", group: "评分", higherIsBetter: true, fmt: "score" },
  { key: "risk_score", label: "风险评分", group: "评分", higherIsBetter: false, fmt: "score" },
  { key: "top10_concentration", label: "前10集中度", group: "集中度", higherIsBetter: null, fmt: "pct" },
  { key: "scale", label: "规模 (亿)", group: "规模", higherIsBetter: null, fmt: "num2" },
];

// ---- 工具函数 ----

function asNumber(v: unknown): number | null {
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (!Number.isNaN(n)) return n;
  }
  return null;
}

function asString(v: unknown): string | null {
  if (typeof v === "string" && v !== "") return v;
  if (v === null || v === undefined) return null;
  return String(v);
}

function styleLabelOf(name: string): string {
  return STYLE_LABELS[name] ?? name;
}

function formatCell(
  value: unknown,
  fmt: "score" | "pct" | "num2" | "num3"
): CompareCell {
  const n = asNumber(value);
  if (n === null) return { text: "—", raw: null };
  switch (fmt) {
    case "score":
      return { text: n.toFixed(1), raw: n };
    case "pct":
      return {
        text: n <= 1 ? `${(n * 100).toFixed(2)}%` : n.toFixed(2),
        raw: n,
      };
    case "num2":
      return { text: n.toFixed(2), raw: n };
    case "num3":
      return { text: n.toFixed(3), raw: n };
  }
}

function getStyleExposure(fund: Record<string, unknown>): Record<string, unknown> {
  const v = fund.style_exposure ?? fund.style ?? fund.exposure;
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>;
  }
  return {};
}

function parseCodes(input: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of input.split(/[,，\s]+/)) {
    const c = part.trim();
    if (!c) continue;
    if (seen.has(c)) continue;
    seen.add(c);
    out.push(c);
  }
  return out;
}

function buildSimilarityMatrix(
  sm: Record<string, unknown> | null,
  codes: string[]
): SimilarityMatrix | null {
  if (!sm) return null;
  const rowCodes = codes.filter(
    (c) => sm[c] && typeof sm[c] === "object" && !Array.isArray(sm[c])
  );
  if (rowCodes.length === 0) return null;
  const colCodes = codes;
  const values: Record<string, Record<string, number | null>> = {};
  for (const r of rowCodes) {
    values[r] = {};
    const rowObj = sm[r] as Record<string, unknown>;
    for (const c of colCodes) {
      values[r][c] = asNumber(rowObj[c]);
    }
  }
  return { rowCodes, colCodes, values };
}

// ---- 页面组件 ----

export default function FundComparePage() {
  const navigate = useNavigate();
  const [codesInput, setCodesInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [hasCompared, setHasCompared] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [funds, setFunds] = useState<FundColumn[]>([]);
  const [similarity, setSimilarity] = useState<SimilarityMatrix | null>(null);

  const parsedCodes = useMemo(() => parseCodes(codesInput), [codesInput]);
  const overLimit = parsedCodes.length > MAX_FUNDS;
  const effectiveCodes = parsedCodes.slice(0, MAX_FUNDS);

  async function handleCompare() {
    if (parsedCodes.length < 2) {
      setError("请至少输入 2 个基金代码进行对比");
      return;
    }
    if (overLimit) {
      setError(`最多支持 ${MAX_FUNDS} 只基金对比，将只对比前 ${MAX_FUNDS} 个`);
    } else {
      setError(null);
    }
    setLoading(true);
    setHasCompared(true);
    try {
      const res = await api.compareFunds(effectiveCodes);
      const data = res.data;
      if (!data) {
        setError(res.warnings.join("; ") || "对比失败");
        setFunds([]);
        setSimilarity(null);
        return;
      }
      const cols: FundColumn[] = effectiveCodes.map((code) => {
        const info = (data.basic_info ?? {})[code] as Record<string, unknown> | undefined;
        const compData = (data.comparison_data ?? {})[code] as Record<string, unknown> | undefined;
        // 合并 basic_info 和 comparison_data，basic_info 字段优先用于基本信息
        const merged: Record<string, unknown> = { ...(compData ?? {}), ...(info ?? {}) };
        return {
          fund_code: code,
          short_name:
            asString(info?.short_name) ??
            asString(info?.name) ??
            asString(compData?.short_name) ??
            null,
          raw: merged,
        };
      });
      setFunds(cols);
      setSimilarity(buildSimilarityMatrix(data.similarity_matrix, effectiveCodes));
    } catch (e) {
      setError(e instanceof Error ? e.message : "对比失败");
      setFunds([]);
      setSimilarity(null);
    } finally {
      setLoading(false);
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleCompare();
    }
  };

  const crumbs: BreadcrumbItem[] = [
    { label: "基金研究" },
    { label: "基金对比" },
  ];

  // ---- 构建对比行 ----

  // 风格暴露子维度并集（保留出现顺序）
  const styleKeys = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const f of funds) {
      const se = getStyleExposure(f.raw);
      for (const k of Object.keys(se)) {
        if (!seen.has(k)) {
          seen.add(k);
          out.push(k);
        }
      }
    }
    return out;
  }, [funds]);

  const rows: CompareRow[] = useMemo(() => {
    const out: CompareRow[] = [];

    // 固定维度
    for (const dim of FIXED_DIMS) {
      out.push({
        group: dim.group,
        label: dim.label,
        higherIsBetter: dim.higherIsBetter,
        cells: funds.map((f) => formatCell(f.raw[dim.key], dim.fmt)),
      });
    }

    // 风格暴露子维度
    if (styleKeys.length > 0) {
      for (const k of styleKeys) {
        out.push({
          group: "风格暴露",
          label: styleLabelOf(k),
          higherIsBetter: null,
          cells: funds.map((f) => formatCell(getStyleExposure(f.raw)[k], "num3")),
        });
      }
    }

    return out;
  }, [funds, styleKeys]);

  // 找出每行的最佳值索引（用于高亮）
  function bestIndex(row: CompareRow): number {
    if (row.higherIsBetter === null) return -1;
    let best = -1;
    let bestVal: number | null = null;
    row.cells.forEach((c, i) => {
      if (c.raw === null) return;
      if (bestVal === null) {
        bestVal = c.raw;
        best = i;
      } else if (row.higherIsBetter ? c.raw > bestVal : c.raw < bestVal) {
        bestVal = c.raw;
        best = i;
      }
    });
    return best;
  }

  // 按分组聚合行（用于渲染分组标题）
  const groupedRows = useMemo(() => {
    const groups: { group: string; rows: CompareRow[] }[] = [];
    let current: { group: string; rows: CompareRow[] } | null = null;
    for (const r of rows) {
      if (!current || current.group !== r.group) {
        current = { group: r.group, rows: [] };
        groups.push(current);
      }
      current.rows.push(r);
    }
    return groups;
  }, [rows]);

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1 mb-4">
        <h1>基金对比</h1>
        <div className="text-sm text-tertiary mt-2">
          横向对比多只基金的评分、风格暴露、集中度与规模（最多 {MAX_FUNDS} 只）
        </div>
      </div>

      {/* 输入表单 */}
      <div
        className="fade-up fade-up-2 mb-4"
        style={{
          background: "var(--surface-raised)",
          border: "1px solid var(--border-hairline)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-4)",
        }}
      >
        <SectionHeader title="选择对比基金" subtitle="用逗号或空格分隔多个基金代码" />
        <div
          style={{
            display: "flex",
            gap: "var(--space-3)",
            alignItems: "end",
            marginTop: "var(--space-3)",
            flexWrap: "wrap",
          }}
        >
          <label className="form-label" style={{ flex: 1, minWidth: 280 }}>
            <span>基金代码</span>
            <input
              type="text"
              className="form-input"
              value={codesInput}
              onChange={(e) => setCodesInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="如 000001, 163406, 110011"
              style={{ fontFamily: "var(--font-mono)" }}
            />
          </label>
          <button
            className="btn btn-primary"
            onClick={handleCompare}
            disabled={loading || parsedCodes.length < 2}
          >
            {loading ? "对比中…" : "对比"}
          </button>
        </div>

        {/* 已解析代码芯片 */}
        {parsedCodes.length > 0 && (
          <div
            style={{
              display: "flex",
              gap: "var(--space-2)",
              flexWrap: "wrap",
              marginTop: "var(--space-3)",
              alignItems: "center",
            }}
          >
            <span className="text-tertiary" style={{ fontSize: "0.75rem" }}>
              已解析 {parsedCodes.length} 个：
            </span>
            {parsedCodes.map((c, i) => (
              <span
                key={c}
                style={{
                  padding: "2px 10px",
                  borderRadius: "var(--radius-xs)",
                  background:
                    i >= MAX_FUNDS ? "var(--negative-soft)" : "var(--accent-soft)",
                  color: i >= MAX_FUNDS ? "var(--negative)" : "var(--accent-hover)",
                  fontFamily: "var(--font-mono)",
                  fontSize: "0.78rem",
                  fontWeight: 600,
                }}
              >
                {c}
                {i >= MAX_FUNDS && " (超额)"}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 错误提示 */}
      {error && (
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
              {error}
            </span>
            <button className="btn btn-ghost btn-sm" onClick={() => setError(null)}>
              关闭
            </button>
          </div>
        </div>
      )}

      {/* 汇总指标 */}
      {hasCompared && !error && funds.length > 0 && (
        <div className="grid grid-3 fade-up fade-up-3 mb-4">
          <MetricCard label="对比基金数" value={funds.length} />
          <MetricCard label="对比维度" value={rows.length} />
          <MetricCard
            label="风格暴露维度"
            value={styleKeys.length}
            sub={styleKeys.map(styleLabelOf).join("、") || "无"}
          />
        </div>
      )}

      {/* 对比表格 */}
      <div className="fade-up fade-up-3">
        <SectionHeader
          title="维度对比"
          subtitle={
            hasCompared
              ? loading
                ? "对比中…"
                : `${funds.length} 只基金 · ${rows.length} 个维度`
              : "请输入基金代码后点击对比"
          }
        />
        <div style={{ marginTop: "var(--space-3)" }}>
          {error && funds.length === 0 ? (
            <ErrorState desc={error} onRetry={handleCompare} />
          ) : loading ? (
            <LoadingState rows={6} cols={Math.max(4, funds.length + 1)} />
          ) : !hasCompared ? (
            <EmptyState
              icon="∅"
              title="尚未对比"
              desc="输入至少 2 个基金代码（用逗号或空格分隔）后点击「对比」"
            />
          ) : funds.length === 0 ? (
            <EmptyState
              icon="∅"
              title="暂无对比数据"
              desc="后端未返回基金数据，请确认基金代码是否正确"
            />
          ) : (
            <div
              style={{
                background: "var(--surface-raised)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-hairline)",
                overflow: "auto",
              }}
            >
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: "160px" }}>维度</th>
                    {funds.map((f, ci) => (
                      <th key={f.fund_code || `col-${ci}`} style={{ textAlign: "right" }}>
                        {f.fund_code ? (
                          <button
                            style={{
                              background: "transparent",
                              border: "none",
                              padding: 0,
                              cursor: "pointer",
                              color: "var(--accent)",
                              fontWeight: 600,
                              fontFamily: "var(--font-mono)",
                              fontSize: "0.78rem",
                            }}
                            onClick={() => navigate(`/funds/${f.fund_code}`)}
                            title={f.short_name ?? f.fund_code}
                          >
                            {f.fund_code}
                          </button>
                        ) : (
                          <span className="text-tertiary">—</span>
                        )}
                        {f.short_name && (
                          <div
                            style={{
                              fontFamily: "var(--font-body)",
                              fontWeight: 400,
                              fontSize: "0.7rem",
                              color: "var(--ink-tertiary)",
                              textTransform: "none",
                              letterSpacing: 0,
                              marginTop: 2,
                            }}
                          >
                            {f.short_name}
                          </div>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {groupedRows.map((g) =>
                    g.rows.map((row, ri) => {
                      const bi = bestIndex(row);
                      const isGroupFirst = ri === 0;
                      return (
                        <tr key={`${g.group}-${row.label}`}>
                          <td
                            style={{
                              paddingLeft: isGroupFirst ? "var(--space-3)" : "var(--space-5)",
                              color: "var(--ink-secondary)",
                              fontWeight: isGroupFirst ? 600 : 400,
                            }}
                          >
                            {isGroupFirst && (
                              <span
                                style={{
                                  fontSize: "0.65rem",
                                  textTransform: "uppercase",
                                  letterSpacing: "0.04em",
                                  color: "var(--ink-tertiary)",
                                  display: "block",
                                  marginBottom: 2,
                                }}
                              >
                                {g.group}
                              </span>
                            )}
                            {row.label}
                          </td>
                          {row.cells.map((c, ci) => (
                            <td
                              key={ci}
                              className="numeric"
                              style={{
                                color:
                                  ci === bi
                                    ? "var(--positive)"
                                    : "var(--ink-secondary)",
                                fontWeight: ci === bi ? 700 : 500,
                              }}
                            >
                              {c.text}
                            </td>
                          ))}
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* 相似度矩阵 */}
      {hasCompared && !loading && similarity && funds.length > 0 && (
        <div
          className="fade-up fade-up-4"
          style={{ marginTop: "var(--space-6)" }}
        >
          <SectionHeader
            title="相似度矩阵"
            subtitle="基金两两之间的相似度（越接近 1 越相似）"
          />
          <div
            style={{
              marginTop: "var(--space-3)",
              background: "var(--surface-raised)",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--border-hairline)",
              overflow: "auto",
            }}
          >
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: "120px" }}>基金</th>
                  {similarity.colCodes.map((c) => (
                    <th key={c} className="numeric">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {similarity.rowCodes.map((r) => (
                  <tr key={r}>
                    <td>
                      <button
                        style={{
                          background: "transparent",
                          border: "none",
                          padding: 0,
                          cursor: "pointer",
                          color: "var(--accent)",
                          fontWeight: 600,
                          fontFamily: "var(--font-mono)",
                          fontSize: "0.82rem",
                        }}
                        onClick={() => navigate(`/funds/${r}`)}
                      >
                        {r}
                      </button>
                    </td>
                    {similarity.colCodes.map((c) => {
                      const v = similarity.values[r][c];
                      const isSelf = r === c;
                      return (
                        <td
                          key={c}
                          className="numeric"
                          style={{
                            color: isSelf
                              ? "var(--ink-tertiary)"
                              : v !== null && v >= 0.8
                              ? "var(--accent)"
                              : "var(--ink-secondary)",
                            fontWeight: isSelf ? 400 : 600,
                          }}
                        >
                          {v === null ? "—" : v.toFixed(3)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
