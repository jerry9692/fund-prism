// 基金画像指纹管理 — 批量生成 + 多基金指纹对比
// 入口：侧边栏「指纹管理」

import { useState } from "react";
import { api } from "../api/client";
import {
  Breadcrumb,
  MetricCard,
  SectionHeader,
  ExportButton,
  ErrorState,
  type BreadcrumbItem,
} from "../components/display";

interface BatchResult {
  total: number;
  success_count: number;
  failure_count: number;
  errors: Array<{ fund_code: string; error: string }>;
  calc_date: string | null;
}

interface CompareResult {
  fund_codes: string[];
  comparison_data: Record<string, unknown>;
  similarity_matrix: Record<string, unknown>;
  overlap_analysis: Record<string, unknown>;
  missing_codes: string[];
}

const crumbs: BreadcrumbItem[] = [{ label: "指纹管理" }];

function parseCodeList(text: string): string[] {
  return text
    .split(/[\s,，;；\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function FingerprintPage() {
  const [batchInput, setBatchInput] = useState("");
  const [batchCalcDate, setBatchCalcDate] = useState("");
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchResult, setBatchResult] = useState<BatchResult | null>(null);
  const [batchError, setBatchError] = useState<string | null>(null);

  const [compareInput, setCompareInput] = useState("");
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);

  const batchCodes = parseCodeList(batchInput);
  const compareCodes = parseCodeList(compareInput);

  async function runBatch() {
    if (batchCodes.length === 0) {
      setBatchError("请输入至少 1 只基金代码");
      return;
    }
    setBatchLoading(true);
    setBatchError(null);
    setBatchResult(null);
    try {
      const resp = await api.batchFingerprint({
        fund_codes: batchCodes,
        calc_date: batchCalcDate || null,
      });
      if (resp.data) {
        setBatchResult(resp.data);
      } else {
        setBatchError(resp.warnings.join("; ") || "批量生成失败");
      }
    } catch (e) {
      setBatchError(e instanceof Error ? e.message : String(e));
    } finally {
      setBatchLoading(false);
    }
  }

  async function runCompare() {
    if (compareCodes.length < 2) {
      setCompareError("请输入至少 2 只基金代码进行对比");
      return;
    }
    setCompareLoading(true);
    setCompareError(null);
    setCompareResult(null);
    try {
      const resp = await api.compareFingerprints(compareCodes);
      if (resp.data) {
        setCompareResult(resp.data);
      } else {
        setCompareError(resp.warnings.join("; ") || "指纹对比失败");
      }
    } catch (e) {
      setCompareError(e instanceof Error ? e.message : String(e));
    } finally {
      setCompareLoading(false);
    }
  }

  return (
    <div>
      <Breadcrumb items={crumbs} />

      <div className="fade-up fade-up-1 mb-4">
        <h1>基金画像指纹</h1>
        <div className="text-sm text-tertiary mt-2">
          批量生成基金指纹向量、多基金指纹相似度对比
        </div>
      </div>

      {/* 双列布局：批量生成 | 指纹对比 */}
      <div className="grid grid-2 fade-up fade-up-2">
        {/* ---- 批量生成 ---- */}
        <div>
          <SectionHeader title="批量生成指纹" subtitle={`已输入 ${batchCodes.length} 只基金`} />
          <div
            style={{
              marginTop: "var(--space-3)",
              padding: "var(--space-4)",
              background: "var(--surface-raised)",
              border: "1px solid var(--border-hairline)",
              borderRadius: "var(--radius-md)",
            }}
          >
            <label className="form-label" style={{ display: "block" }}>
              <span>基金代码（空格/逗号/换行分隔）</span>
              <textarea
                className="form-input"
                rows={4}
                value={batchInput}
                onChange={(e) => setBatchInput(e.target.value)}
                placeholder="000001, 020005, 070002"
                style={{ fontFamily: "var(--font-mono)", resize: "vertical" }}
              />
            </label>
            <label className="form-label mt-3" style={{ display: "block" }}>
              <span>计算日期（可选，默认今天）</span>
              <input
                className="form-input"
                type="date"
                value={batchCalcDate}
                onChange={(e) => setBatchCalcDate(e.target.value)}
              />
            </label>
            <div className="mt-3 flex items-center gap-2">
              <button
                className="btn btn-primary btn-sm"
                onClick={runBatch}
                disabled={batchLoading || batchCodes.length === 0}
              >
                {batchLoading ? "生成中..." : "批量生成"}
              </button>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setBatchInput("");
                  setBatchCalcDate("");
                  setBatchResult(null);
                  setBatchError(null);
                }}
              >
                清空
              </button>
            </div>

            {batchError && (
              <div className="mt-3">
                <ErrorState title="批量生成失败" desc={batchError} />
              </div>
            )}

            {batchResult && (
              <div
                className="mt-4"
                style={{
                  padding: "var(--space-3) var(--space-4)",
                  background: "var(--surface-sunken)",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border-hairline)",
                }}
              >
                <div
                  className="grid"
                  style={{
                    gridTemplateColumns: "repeat(3, 1fr)",
                    gap: "var(--space-3)",
                    marginBottom: "var(--space-3)",
                  }}
                >
                  <MetricCard label="总计" value={batchResult.total} />
                  <MetricCard
                    label="成功"
                    value={batchResult.success_count}
                    positive={batchResult.success_count > 0}
                  />
                  <MetricCard
                    label="失败"
                    value={batchResult.failure_count}
                    negative={batchResult.failure_count > 0}
                  />
                </div>
                {batchResult.errors.length > 0 && (
                  <div>
                    <div className="text-xs text-tertiary mb-1">错误明细：</div>
                    <div
                      className="mono text-xs"
                      style={{
                        maxHeight: "120px",
                        overflow: "auto",
                        padding: "var(--space-2)",
                        background: "var(--surface-base)",
                        borderRadius: "var(--radius-xs)",
                      }}
                    >
                      {batchResult.errors.map((e) => (
                        <div key={e.fund_code} style={{ color: "var(--negative)" }}>
                          {e.fund_code}: {e.error}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* ---- 指纹对比 ---- */}
        <div>
          <SectionHeader title="指纹对比" subtitle={`已输入 ${compareCodes.length} 只基金（需 ≥2）`} />
          <div
            style={{
              marginTop: "var(--space-3)",
              padding: "var(--space-4)",
              background: "var(--surface-raised)",
              border: "1px solid var(--border-hairline)",
              borderRadius: "var(--radius-md)",
            }}
          >
            <label className="form-label" style={{ display: "block" }}>
              <span>基金代码（2-6 只）</span>
              <textarea
                className="form-input"
                rows={4}
                value={compareInput}
                onChange={(e) => setCompareInput(e.target.value)}
                placeholder="000001, 020005"
                style={{ fontFamily: "var(--font-mono)", resize: "vertical" }}
              />
            </label>
            <div className="mt-3 flex items-center gap-2">
              <button
                className="btn btn-primary btn-sm"
                onClick={runCompare}
                disabled={compareLoading || compareCodes.length < 2}
              >
                {compareLoading ? "对比中..." : "对比指纹"}
              </button>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setCompareInput("");
                  setCompareResult(null);
                  setCompareError(null);
                }}
              >
                清空
              </button>
            </div>

            {compareError && (
              <div className="mt-3">
                <ErrorState title="指纹对比失败" desc={compareError} />
              </div>
            )}

            {compareResult && (
              <div className="mt-4">
                <div
                  className="grid"
                  style={{
                    gridTemplateColumns: "repeat(2, 1fr)",
                    gap: "var(--space-3)",
                    marginBottom: "var(--space-3)",
                  }}
                >
                  <MetricCard
                    label="有效指纹"
                    value={compareResult.fund_codes.length}
                    positive
                  />
                  <MetricCard
                    label="缺失指纹"
                    value={compareResult.missing_codes.length}
                    negative={compareResult.missing_codes.length > 0}
                  />
                </div>

                {compareResult.fund_codes.length >= 2 && (
                  <div
                    style={{
                      padding: "var(--space-3) var(--space-4)",
                      background: "var(--surface-sunken)",
                      borderRadius: "var(--radius-sm)",
                    }}
                  >
                    <div className="text-xs text-tertiary mb-2">
                      相似度矩阵
                    </div>
                    <SimilarityMatrix
                      codes={compareResult.fund_codes}
                      matrix={compareResult.similarity_matrix as Record<string, Record<string, number>>}
                    />
                  </div>
                )}

                {compareResult.missing_codes.length > 0 && (
                  <div className="text-xs text-tertiary mt-2">
                    无指纹基金：{compareResult.missing_codes.join(", ")}
                  </div>
                )}

                {compareResult.fund_codes.length >= 2 && (
                  <div className="mt-3">
                    <ExportButton
                      data={compareResult}
                      filename={`fingerprint_compare_${compareResult.fund_codes.join("_")}.json`}
                      label="导出 JSON"
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 使用说明 */}
      <div
        className="fade-up fade-up-3 mt-6"
        style={{
          padding: "var(--space-4)",
          background: "var(--surface-sunken)",
          borderRadius: "var(--radius-md)",
          fontSize: "0.82rem",
          color: "var(--ink-tertiary)",
        }}
      >
        <div className="font-semibold mb-2" style={{ color: "var(--ink-secondary)" }}>
          使用说明
        </div>
        <ul style={{ paddingLeft: "1.2em", lineHeight: 1.7 }}>
          <li>批量生成：为指定基金计算画像指纹向量（含风格暴露、收益特征、持仓特征等维度），结果持久化到数据库</li>
          <li>指纹对比：比较 2-6 只基金的指纹相似度，输出相似度矩阵与持仓重叠分析</li>
          <li>建议先批量生成指纹，再进行对比；未生成指纹的基金无法参与对比</li>
          <li>单基金的相似基金搜索可在「相似搜索」页面进行</li>
        </ul>
      </div>
    </div>
  );
}

function SimilarityMatrix({
  codes,
  matrix,
}: {
  codes: string[];
  matrix: Record<string, Record<string, number>>;
}) {
  if (!matrix || Object.keys(matrix).length === 0) {
    return <div className="text-sm text-tertiary">暂无相似度数据</div>;
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table
        className="mono text-xs"
        style={{ borderCollapse: "collapse", width: "100%" }}
      >
        <thead>
          <tr>
            <th style={{ padding: "4px 8px", textAlign: "left", fontWeight: 600 }}></th>
            {codes.map((c) => (
              <th key={c} style={{ padding: "4px 8px", textAlign: "right", fontWeight: 600 }}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {codes.map((row) => (
            <tr key={row}>
              <td style={{ padding: "4px 8px", fontWeight: 600 }}>{row}</td>
              {codes.map((col) => {
                const val = matrix[row]?.[col];
                const pct = typeof val === "number" ? Math.round(val * 100) : null;
                const isSelf = row === col;
                let bg = "transparent";
                let color = "var(--ink-primary)";
                if (isSelf) {
                  bg = "var(--accent-soft)";
                  color = "var(--accent)";
                } else if (pct != null) {
                  if (pct >= 70) bg = "var(--positive-soft)";
                  else if (pct >= 40) bg = "var(--warning-soft)";
                  else bg = "var(--negative-soft)";
                }
                return (
                  <td
                    key={col}
                    style={{
                      padding: "4px 8px",
                      textAlign: "right",
                      background: bg,
                      color,
                      borderRadius: "2px",
                    }}
                  >
                    {pct != null ? `${pct}%` : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
