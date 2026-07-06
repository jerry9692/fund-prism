// API 调试页 — 前端原生的 API playground
// 直接调用后端任意端点，展示完整响应结构（data/metadata/evidence/warnings/conclusion_status）
// 纯前端实现，无需后端 /api-debug 端点（P2.5-4 的"API 调试"部分）

import { useState } from "react";
import {
  SectionHeader,
  Breadcrumb,
  LoadingState,
  EmptyState,
  ErrorState,
  TabNav,
  type BreadcrumbItem,
} from "../components/display";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface DebugResponse {
  ok: boolean;
  status: number;
  statusText: string;
  durationMs: number;
  body: unknown;
  rawText: string;
}

interface PresetEndpoint {
  method: Method;
  path: string;
  label: string;
  body?: string;
}

const PRESETS: PresetEndpoint[] = [
  { method: "GET", path: "/api/v1/health", label: "健康检查" },
  { method: "GET", path: "/api/v1/funds/search?q=000001&limit=5", label: "基金搜索" },
  { method: "POST", path: "/api/v1/funds/screen", label: "基金筛选", body: '{"filters":{},"limit":20}' },
  { method: "GET", path: "/api/v1/funds/000001/profile", label: "基金档案" },
  { method: "GET", path: "/api/v1/funds/000001/nav-metrics", label: "净值指标" },
  { method: "GET", path: "/api/v1/funds/000001/holdings", label: "持仓明细" },
  { method: "POST", path: "/api/v1/analysis/exposure", label: "风格暴露", body: '{"fund_code":"000001","window":60}' },
  { method: "POST", path: "/api/v2/research/packet", label: "研究包(v2)", body: '{"fund_code":"000001","template":"single_fund_checkup"}' },
  { method: "GET", path: "/api/v2/research/packets?limit=20", label: "研究包列表(v2)" },
  { method: "GET", path: "/api/v2/experiments", label: "实验列表" },
  { method: "GET", path: "/api/v2/validation/p2b/latest", label: "最新验收报告" },
  { method: "GET", path: "/api/v2/analysis/scoring/backtest", label: "评分回测列表" },
  { method: "GET", path: "/api/v2/analysis/simulated-holding?fund_code=000001&limit=5", label: "模拟持仓列表" },
  { method: "GET", path: "/api/v2/reviewer-annotations/funds/000001/status", label: "基金审核状态" },
];

type ResponseTab = "data" | "metadata" | "evidence" | "warnings" | "conclusion_status" | "raw";

function prettyJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

export default function ApiDebugPage() {
  const [method, setMethod] = useState<Method>("GET");
  const [path, setPath] = useState("/api/v1/health");
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resp, setResp] = useState<DebugResponse | null>(null);
  const [activeTab, setActiveTab] = useState<ResponseTab>("data");

  async function handleSend() {
    if (!path.trim()) {
      setError("请输入请求路径");
      return;
    }
    setLoading(true);
    setError(null);
    setResp(null);
    const start = performance.now();
    try {
      const init: RequestInit = { method };
      if (method !== "GET" && method !== "DELETE" && body.trim()) {
        init.body = body.trim();
        init.headers = { "Content-Type": "application/json" };
      }
      const res = await fetch(`${BASE_URL}${path.trim()}`, init);
      const rawText = await res.text();
      const durationMs = Math.round(performance.now() - start);
      let bodyJson: unknown = null;
      try {
        bodyJson = rawText ? JSON.parse(rawText) : null;
      } catch {
        bodyJson = rawText;
      }
      setResp({
        ok: res.ok,
        status: res.status,
        statusText: res.statusText,
        durationMs,
        body: bodyJson,
        rawText,
      });
    } catch (e) {
      setError(`请求异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }

  function applyPreset(p: PresetEndpoint) {
    setMethod(p.method);
    setPath(p.path);
    setBody(p.body ?? "");
    setResp(null);
    setError(null);
  }

  // 解析 APIResponse 结构
  const apiBody = resp?.body as
    | {
        data?: unknown;
        metadata?: unknown;
        evidence?: unknown;
        warnings?: unknown;
        conclusion_status?: string;
        not_applicable_reason?: string | null;
      }
    | null;

  const tabs = [
    { key: "data", label: "data" },
    { key: "metadata", label: "metadata" },
    { key: "evidence", label: "evidence" },
    { key: "warnings", label: "warnings" },
    { key: "conclusion_status", label: "conclusion_status" },
    { key: "raw", label: "raw" },
  ];

  const crumbs: BreadcrumbItem[] = [
    { label: "系统" },
    { label: "API 调试" },
  ];

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1" style={{ marginTop: "var(--space-3)", marginBottom: "var(--space-4)" }}>
        <h1>API 调试</h1>
        <div className="text-sm text-tertiary" style={{ marginTop: "var(--space-2)" }}>
          直接调用后端任意端点，检视完整响应结构与结论可信度字段
        </div>
      </div>

      {/* 预设端点 */}
      <div className="fade-up fade-up-2" style={{ marginBottom: "var(--space-4)" }}>
        <SectionHeader title="常用端点" subtitle="点击快速填充请求参数" />
        <div
          className="grid"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
            gap: "var(--space-2)",
            marginTop: "var(--space-3)",
          }}
        >
          {PRESETS.map((p) => (
            <button
              key={`${p.method}-${p.path}`}
              className="btn btn-secondary btn-sm"
              style={{ textAlign: "left", justifyContent: "flex-start" }}
              onClick={() => applyPreset(p)}
            >
              <span className="mono" style={{ color: "var(--accent)", fontWeight: 600, marginRight: "6px" }}>
                {p.method}
              </span>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* 请求表单 */}
      <form
        className="fade-up fade-up-2"
        style={{
          background: "var(--surface-raised)",
          border: "1px solid var(--border-hairline)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-4)",
          marginBottom: "var(--space-4)",
        }}
        onSubmit={(e) => {
          e.preventDefault();
          handleSend();
        }}
      >
        <SectionHeader title="请求构造" />
        <div
          className="grid"
          style={{
            gridTemplateColumns: "100px 1fr auto",
            gap: "var(--space-3)",
            marginTop: "var(--space-3)",
            alignItems: "end",
          }}
        >
          <label className="form-label">
            <span>方法</span>
            <select
              className="form-input"
              value={method}
              onChange={(e) => setMethod(e.target.value as Method)}
            >
              {(["GET", "POST", "PUT", "PATCH", "DELETE"] as Method[]).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="form-label">
            <span>路径（相对路径，不含 host）</span>
            <input
              type="text"
              className="form-input"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="/api/v1/..."
              style={{ fontFamily: "var(--font-mono)" }}
            />
          </label>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading || !path.trim()}
          >
            {loading ? "发送中..." : "发送请求"}
          </button>
        </div>
        {method !== "GET" && method !== "DELETE" && (
          <label className="form-label" style={{ display: "block", marginTop: "var(--space-3)" }}>
            <span>请求体 (JSON)</span>
            <textarea
              className="form-input"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={5}
              placeholder='{"key": "value"}'
              style={{
                width: "100%",
                height: "auto",
                resize: "vertical",
                fontFamily: "var(--font-mono)",
                fontSize: "0.8rem",
                lineHeight: 1.5,
              }}
            />
          </label>
        )}
      </form>

      {/* 错误 */}
      {error && (
        <div className="fade-up fade-up-3" style={{ marginBottom: "var(--space-4)" }}>
          <ErrorState title="请求失败" desc={error} />
        </div>
      )}

      {/* 加载 */}
      {loading && (
        <div className="fade-up fade-up-3">
          <LoadingState rows={3} cols={6} />
        </div>
      )}

      {/* 响应 */}
      {!loading && !error && resp && (
        <div className="fade-up fade-up-3">
          {/* 状态行 */}
          <div
            style={{
              display: "flex",
              gap: "var(--space-4)",
              alignItems: "center",
              marginBottom: "var(--space-3)",
              padding: "var(--space-2) var(--space-4)",
              background: "var(--surface-raised)",
              border: "1px solid var(--border-hairline)",
              borderRadius: "var(--radius-md)",
              fontSize: "0.85rem",
            }}
          >
            <span
              className="mono"
              style={{
                fontWeight: 600,
                color: resp.ok ? "var(--positive)" : "var(--negative)",
              }}
            >
              {resp.status} {resp.statusText}
            </span>
            <span className="text-sm text-tertiary">耗时 {resp.durationMs} ms</span>
            {apiBody && (
              <span className="text-sm text-tertiary">
                conclusion:{" "}
                <span className="mono" style={{ color: "var(--accent)" }}>
                  {apiBody.conclusion_status ?? "—"}
                </span>
              </span>
            )}
          </div>

          {/* 非标准响应（非 APIResponse 结构） */}
          {!apiBody || typeof apiBody !== "object" ? (
            <div
              style={{
                background: "var(--surface-raised)",
                border: "1px solid var(--border-hairline)",
                borderRadius: "var(--radius-md)",
                padding: "var(--space-4)",
              }}
            >
              <SectionHeader title="响应体" subtitle="非标准 APIResponse 结构，原样展示" />
              <pre
                className="mono"
                style={{
                  marginTop: "var(--space-3)",
                  padding: "var(--space-3)",
                  background: "var(--surface-sunken)",
                  borderRadius: "var(--radius-sm)",
                  fontSize: "0.8rem",
                  lineHeight: 1.5,
                  overflow: "auto",
                  maxHeight: "60vh",
                  margin: 0,
                }}
              >
                {prettyJson(resp.body)}
              </pre>
            </div>
          ) : (
            <>
              {/* Tab 切换 */}
              <TabNav tabs={tabs} active={activeTab} onChange={(k) => setActiveTab(k as ResponseTab)} />

              <div
                style={{
                  marginTop: "var(--space-3)",
                  background: "var(--surface-raised)",
                  border: "1px solid var(--border-hairline)",
                  borderRadius: "var(--radius-md)",
                  padding: "var(--space-4)",
                }}
              >
                <pre
                  className="mono"
                  style={{
                    padding: "var(--space-3)",
                    background: "var(--surface-sunken)",
                    borderRadius: "var(--radius-sm)",
                    fontSize: "0.8rem",
                    lineHeight: 1.5,
                    overflow: "auto",
                    maxHeight: "60vh",
                    margin: 0,
                  }}
                >
                  {prettyJson(
                    activeTab === "raw"
                      ? resp.body
                      : (apiBody as Record<string, unknown>)[activeTab]
                  )}
                </pre>
              </div>
            </>
          )}
        </div>
      )}

      {/* 初始空状态 */}
      {!loading && !error && !resp && (
        <div className="fade-up fade-up-3">
          <EmptyState
            icon="⚙"
            title="选择预设端点或手动构造请求"
            desc="发送请求后将展示 HTTP 状态、结论状态、以及 data/metadata/evidence/warnings 等字段"
          />
        </div>
      )}
    </div>
  );
}
