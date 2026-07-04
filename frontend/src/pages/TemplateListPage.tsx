// 研究任务模板 — 内置模板植入 / 模板列表 / 执行 / 执行记录
// 模板由后端管理，前端负责展示、填入输入参数并触发执行

import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import {
  SectionHeader,
  StatusBadge,
  EmptyState,
  LoadingState,
  ErrorState,
  Breadcrumb,
  MetricCard,
  Drawer,
  type BreadcrumbItem,
} from "../components/display";

// ---- 防御式取值（后端返回 Record<string, unknown>）----
function asString(v: unknown): string {
  return typeof v === "string" ? v : v == null ? "" : String(v);
}
function asNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  const n = typeof v === "string" ? Number(v) : NaN;
  return Number.isFinite(n) ? n : null;
}
function asBool(v: unknown): boolean {
  return v === true || v === 1 || asString(v).toLowerCase() === "true";
}
function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}
function asObject(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

interface TemplateItem {
  template_id: string;
  name: string;
  description: string;
  step_count: number;
  is_builtin: boolean;
  steps: Array<Record<string, unknown>>;
  raw: Record<string, unknown>;
}

function toTemplate(item: Record<string, unknown>): TemplateItem {
  const steps = asArray(item.steps).map((s) => asObject(s));
  const id = asString(item.template_id) || asString(item.id);
  return {
    template_id: id,
    name: asString(item.name) || id,
    description: asString(item.description),
    step_count: asNumber(item.step_count) ?? asNumber(item.steps_count) ?? steps.length,
    is_builtin: asBool(item.is_builtin),
    steps,
    raw: item,
  };
}

function BuiltinBadge({ builtin }: { builtin: boolean }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: "var(--radius-sm)",
        fontSize: "0.7rem",
        fontWeight: 600,
        fontFamily: "var(--font-mono)",
        background: builtin ? "var(--positive-soft)" : "var(--surface-sunken)",
        color: builtin ? "var(--positive)" : "var(--ink-tertiary)",
      }}
    >
      {builtin ? "内置" : "自定义"}
    </span>
  );
}

export default function TemplateListPage() {
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);
  const [seedMsg, setSeedMsg] = useState<string | null>(null);

  // 执行 Drawer
  const [execTemplate, setExecTemplate] = useState<TemplateItem | null>(null);
  const [inputsText, setInputsText] = useState("{}");
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<Record<string, unknown> | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  // 执行记录
  const [runs, setRuns] = useState<Array<Record<string, unknown>>>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listTemplates();
      const items = (res.data?.templates ?? []).map((it) => asObject(it));
      setTemplates(items.map(toTemplate));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载模板失败");
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const res = await api.listTemplateRuns();
      setRuns(asArray(res.data?.runs).map((it) => asObject(it)));
    } catch {
      setRuns([]);
    } finally {
      setRunsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTemplates();
    loadRuns();
  }, [loadTemplates, loadRuns]);

  async function handleSeed() {
    setSeeding(true);
    setSeedMsg(null);
    try {
      const res = await api.seedTemplates();
      const d = res.data;
      const inserted = d?.inserted ?? 0;
      setSeedMsg(
        inserted > 0
          ? `已植入 ${inserted} 个内置模板`
          : "模板已是最新",
      );
      await loadTemplates();
    } catch (e) {
      setSeedMsg(e instanceof Error ? e.message : "植入失败");
    } finally {
      setSeeding(false);
    }
  }

  function openExec(tpl: TemplateItem) {
    setExecTemplate(tpl);
    setInputsText("{}");
    setRunResult(null);
    setRunError(null);
  }

  async function handleRun() {
    if (!execTemplate) return;
    let inputs: Record<string, unknown>;
    try {
      const parsed = JSON.parse(inputsText || "{}");
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        inputs = parsed as Record<string, unknown>;
      } else {
        setRunError("输入必须是 JSON 对象");
        return;
      }
    } catch (e) {
      setRunError(
        `JSON 解析失败：${e instanceof Error ? e.message : String(e)}`,
      );
      return;
    }
    setRunning(true);
    setRunError(null);
    setRunResult(null);
    try {
      const res = await api.runTemplate(execTemplate.template_id, inputs);
      setRunResult(res.data ?? {});
      await loadRuns();
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "执行失败");
    } finally {
      setRunning(false);
    }
  }

  const builtinCount = templates.filter((t) => t.is_builtin).length;
  const customCount = templates.length - builtinCount;

  const crumbs: BreadcrumbItem[] = [
    { label: "基金研究" },
    { label: "研究任务模板" },
  ];

  return (
    <div>
      <Breadcrumb items={crumbs} />

      <div
        className="fade-up fade-up-1"
        style={{ marginTop: "var(--space-3)", marginBottom: "var(--space-4)" }}
      >
        <h1>研究任务模板</h1>
        <div
          className="text-sm text-tertiary"
          style={{ marginTop: "var(--space-2)" }}
        >
          管理可复用的研究流程模板，填入参数后一键执行多步骤分析任务
        </div>
      </div>

      {/* 工具栏 */}
      <div
        className="fade-up fade-up-2"
        style={{
          background: "var(--surface-raised)",
          border: "1px solid var(--border-hairline)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-3) var(--space-4)",
          marginBottom: "var(--space-4)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "var(--space-3)",
        }}
      >
        <div>
          <div style={{ fontWeight: 600 }}>模板管理</div>
          {seedMsg && (
            <div
              className="text-xs text-tertiary"
              style={{ marginTop: 2 }}
            >
              {seedMsg}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={loadTemplates}
            disabled={loading}
          >
            刷新
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={handleSeed}
            disabled={seeding}
          >
            {seeding ? "植入中…" : "植入内置模板"}
          </button>
        </div>
      </div>

      {/* 概览指标 */}
      <div
        className="grid fade-up fade-up-2"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: "var(--space-3)",
          marginBottom: "var(--space-4)",
        }}
      >
        <MetricCard label="模板总数" value={templates.length} />
        <MetricCard label="内置模板" value={builtinCount} />
        <MetricCard label="自定义模板" value={customCount} />
        <MetricCard label="执行记录" value={runs.length} />
      </div>

      {/* 模板列表 */}
      <div className="fade-up fade-up-3">
        <SectionHeader title="模板列表" subtitle="点击「详情」查看步骤定义，点击「执行」填入参数运行" />
        <div style={{ marginTop: "var(--space-3)" }}>
          {loading ? (
            <LoadingState rows={3} cols={3} />
          ) : error ? (
            <ErrorState
              title="加载模板失败"
              desc={error}
              onRetry={loadTemplates}
            />
          ) : templates.length === 0 ? (
            <EmptyState
              icon="∅"
              title="暂无模板"
              desc="点击「植入内置模板」加载系统预置研究流程"
              action={
                <button
                  className="btn btn-primary btn-sm"
                  onClick={handleSeed}
                  disabled={seeding}
                  style={{ marginTop: "var(--space-3)" }}
                >
                  {seeding ? "植入中…" : "植入内置模板"}
                </button>
              }
            />
          ) : (
            templates.map((t) => (
              <div
                key={t.template_id}
                style={{
                  background: "var(--surface-raised)",
                  border: "1px solid var(--border-hairline)",
                  borderRadius: "var(--radius-md)",
                  padding: "var(--space-4)",
                  marginBottom: "var(--space-3)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    justifyContent: "space-between",
                    gap: "var(--space-3)",
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "var(--space-2)",
                        marginBottom: "var(--space-1)",
                      }}
                    >
                      <span
                        style={{ fontWeight: 600, fontSize: "1rem" }}
                      >
                        {t.name}
                      </span>
                      <BuiltinBadge builtin={t.is_builtin} />
                    </div>
                    <div className="text-sm text-tertiary">
                      {t.description || "暂无描述"}
                    </div>
                    <div
                      className="mono text-xs text-tertiary"
                      style={{ marginTop: "var(--space-1)" }}
                    >
                      {t.step_count} 步 · ID: {t.template_id}
                    </div>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "var(--space-2)",
                      alignItems: "flex-end",
                    }}
                  >
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => openExec(t)}
                    >
                      执行
                    </button>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        setExpandedId(
                          expandedId === t.template_id ? null : t.template_id,
                        )
                      }
                    >
                      {expandedId === t.template_id ? "收起" : "详情"}
                    </button>
                  </div>
                </div>

                {expandedId === t.template_id && (
                  <div
                    style={{
                      marginTop: "var(--space-3)",
                      paddingTop: "var(--space-3)",
                      borderTop: "1px dashed var(--border-hairline)",
                    }}
                  >
                    <div
                      className="text-xs text-tertiary"
                      style={{ marginBottom: "var(--space-2)" }}
                    >
                      步骤定义
                    </div>
                    {t.steps.length === 0 ? (
                      <div className="text-sm text-tertiary">
                        该模板暂无步骤定义
                      </div>
                    ) : (
                      <ol
                        style={{
                          margin: 0,
                          paddingLeft: "var(--space-5)",
                          display: "flex",
                          flexDirection: "column",
                          gap: "var(--space-2)",
                        }}
                      >
                        {t.steps.map((s, i) => {
                          const stepName =
                            asString(s.name) ||
                            asString(s.step_name) ||
                            asString(s.title) ||
                            `步骤 ${i + 1}`;
                          const stepDesc =
                            asString(s.description) || asString(s.desc);
                          return (
                            <li key={i} className="text-sm">
                              <span
                                className="mono text-tertiary"
                                style={{ marginRight: "var(--space-2)" }}
                              >
                                {i + 1}.
                              </span>
                              <span style={{ fontWeight: 600 }}>
                                {stepName}
                              </span>
                              {stepDesc && (
                                <div
                                  className="text-tertiary"
                                  style={{ marginTop: 2 }}
                                >
                                  {stepDesc}
                                </div>
                              )}
                            </li>
                          );
                        })}
                      </ol>
                    )}
                    <details style={{ marginTop: "var(--space-3)" }}>
                      <summary
                        className="text-xs text-tertiary"
                        style={{ cursor: "pointer" }}
                      >
                        查看原始定义
                      </summary>
                      <pre
                        className="mono text-xs"
                        style={{
                          marginTop: "var(--space-2)",
                          padding: "var(--space-3)",
                          background: "var(--surface-sunken)",
                          borderRadius: "var(--radius-sm)",
                          overflow: "auto",
                          maxHeight: 240,
                        }}
                      >
                        {JSON.stringify(t.raw, null, 2)}
                      </pre>
                    </details>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* 执行记录 */}
      <div
        className="fade-up fade-up-4"
        style={{ marginTop: "var(--space-6)" }}
      >
        <SectionHeader
          title="执行记录"
          subtitle="最近的研究任务执行历史"
          actions={
            <button
              className="btn btn-ghost btn-sm"
              onClick={loadRuns}
              disabled={runsLoading}
            >
              刷新
            </button>
          }
        />
        <div style={{ marginTop: "var(--space-3)" }}>
          {runsLoading ? (
            <LoadingState rows={3} cols={3} />
          ) : runs.length === 0 ? (
            <EmptyState
              icon="∅"
              title="暂无执行记录"
              desc="执行一个模板后，记录将出现在此处"
            />
          ) : (
            <div
              className="flex flex-col"
              style={{ gap: "var(--space-2)" }}
            >
              {runs.map((r, i) => {
                const tplName =
                  asString(r.template_name) ||
                  asString(r.template_id) ||
                  "—";
                const status = asString(r.status) || "observation";
                const started =
                  asString(r.started_at) ||
                  asString(r.created_at) ||
                  asString(r.run_at);
                const completed = asNumber(r.steps_completed);
                const total = asNumber(r.steps_total);
                return (
                  <div
                    key={asString(r.run_id) || asString(r.id) || i}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "var(--space-2) var(--space-3)",
                      background: "var(--surface-raised)",
                      border: "1px solid var(--border-hairline)",
                      borderRadius: "var(--radius-sm)",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "var(--space-3)",
                      }}
                    >
                      <StatusBadge status={status} />
                      <span
                        className="text-sm"
                        style={{ fontWeight: 600 }}
                      >
                        {tplName}
                      </span>
                    </div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "var(--space-3)",
                      }}
                    >
                      <span className="mono text-xs text-tertiary">
                        {completed == null ? "—" : completed}/
                        {total == null ? "—" : total} 步
                      </span>
                      <span className="mono text-xs text-tertiary">
                        {started
                          ? new Date(started).toLocaleString("zh-CN")
                          : "—"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* 执行 Drawer */}
      <Drawer
        open={!!execTemplate}
        onClose={() => setExecTemplate(null)}
        title={execTemplate ? `执行模板：${execTemplate.name}` : ""}
      >
        <div
          className="flex flex-col"
          style={{ gap: "var(--space-3)" }}
        >
          <div className="text-sm text-tertiary">
            模板 ID：
            <span className="mono">{execTemplate?.template_id}</span>
            {" · "}
            {execTemplate?.step_count} 步
          </div>
          {execTemplate?.description && (
            <div className="text-sm text-tertiary">
              {execTemplate.description}
            </div>
          )}
          <label className="form-label">
            <span>输入参数 (JSON)</span>
            <textarea
              className="form-textarea"
              value={inputsText}
              onChange={(e) => setInputsText(e.target.value)}
              rows={10}
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "0.82rem",
              }}
              placeholder='{"fund_code":"000001"}'
            />
          </label>
          {runError && (
            <div
              style={{
                color: "var(--negative)",
                fontSize: "0.82rem",
                padding: "var(--space-2) var(--space-3)",
                background: "var(--negative-soft)",
                borderRadius: "var(--radius-sm)",
              }}
            >
              {runError}
            </div>
          )}
          <button
            className="btn btn-primary"
            onClick={handleRun}
            disabled={running}
          >
            {running ? "执行中…" : "开始执行"}
          </button>

          {runResult && (
            <div
              style={{
                marginTop: "var(--space-2)",
                padding: "var(--space-3)",
                background: "var(--surface-sunken)",
                border: "1px solid var(--border-hairline)",
                borderRadius: "var(--radius-sm)",
              }}
            >
              <div
                style={{
                  fontWeight: 600,
                  marginBottom: "var(--space-2)",
                }}
              >
                执行结果
              </div>
              <div
                className="text-sm"
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "var(--space-1)",
                  marginBottom: "var(--space-2)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                  <span>状态：</span>
                  <StatusBadge
                    status={asString(runResult.status) || "observation"}
                  />
                </div>
                <div>
                  步骤进度：
                  <span className="mono">
                    {asNumber(runResult.steps_completed) ?? "—"} /{" "}
                    {asNumber(runResult.steps_total) ?? "—"}
                  </span>
                </div>
              </div>
              {asArray(runResult.step_results).length > 0 && (
                <div style={{ marginBottom: "var(--space-2)" }}>
                  <div
                    className="text-xs text-tertiary"
                    style={{ marginBottom: "var(--space-1)" }}
                  >
                    步骤结果
                  </div>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "var(--space-1)",
                    }}
                  >
                    {asArray(runResult.step_results).map((sr, i) => {
                      const o = asObject(sr);
                      const stepName =
                        asString(o.step_name) ||
                        asString(o.name) ||
                        `步骤 ${i + 1}`;
                      return (
                        <div
                          key={i}
                          className="text-xs"
                          style={{
                            display: "flex",
                            gap: "var(--space-2)",
                            alignItems: "center",
                          }}
                        >
                          <StatusBadge
                            status={asString(o.status) || "observation"}
                          />
                          <span>{stepName}</span>
                          {asString(o.message) && (
                            <span className="text-tertiary">
                              — {asString(o.message)}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              <details style={{ marginTop: "var(--space-2)" }}>
                <summary
                  className="text-xs text-tertiary"
                  style={{ cursor: "pointer" }}
                >
                  查看完整结果
                </summary>
                <pre
                  className="mono text-xs"
                  style={{
                    marginTop: "var(--space-2)",
                    overflow: "auto",
                    maxHeight: 260,
                  }}
                >
                  {JSON.stringify(runResult, null, 2)}
                </pre>
              </details>
            </div>
          )}
        </div>
      </Drawer>
    </div>
  );
}
