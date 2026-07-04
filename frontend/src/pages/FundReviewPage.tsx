import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  api,
  type AnnotationType,
  type EffectiveStatus,
  type ReviewerAnnotation,
  type TargetModule,
} from "../api/client";
import {
  SectionHeader,
  StatusBadge as SharedStatusBadge,
  Breadcrumb,
  MetricCard,
  LoadingState,
  EmptyState,
  ErrorState,
  type BreadcrumbItem,
} from "../components/display";

const ANNOTATION_TYPE_LABELS: Record<AnnotationType, string> = {
  note: "备注",
  lock: "锁定",
  exclude: "排除",
  approve: "批准",
  flag: "标记",
  benchmark_override: "基准调整",
  confidence_override: "置信度调整",
};

const ANNOTATION_TYPE_COLORS: Record<AnnotationType, string> = {
  note: "var(--ink-tertiary)",
  lock: "var(--warning)",
  exclude: "var(--negative)",
  approve: "var(--positive)",
  flag: "var(--accent)",
  benchmark_override: "var(--accent)",
  confidence_override: "var(--accent)",
};

// 审核类型 → 结论状态映射（用于 SharedStatusBadge 着色）
const ANNOTATION_TYPE_TO_CONCLUSION: Record<AnnotationType, string> = {
  note: "observation",
  lock: "estimated",
  exclude: "needs_review",
  approve: "fact",
  flag: "needs_review",
  benchmark_override: "observation",
  confidence_override: "observation",
};

const TARGET_MODULE_LABELS: Record<TargetModule, string> = {
  scoring: "综合评分",
  simulated_holding: "模拟持仓",
  dynamic_attribution: "动态归因",
};

const STATUS_COLORS: Record<EffectiveStatus, string> = {
  open: "var(--ink-tertiary)",
  approved: "var(--positive)",
  locked: "var(--warning)",
  excluded: "var(--negative)",
};

const STATUS_SOFT_BG: Record<EffectiveStatus, string> = {
  open: "var(--surface-sunken)",
  approved: "var(--positive-soft)",
  locked: "var(--warning-soft)",
  excluded: "var(--negative-soft)",
};

const STATUS_LABELS: Record<EffectiveStatus, string> = {
  open: "待审核",
  approved: "已批准",
  locked: "已锁定",
  excluded: "已排除",
};

function ReviewStatusBadge({ status }: { status: EffectiveStatus }) {
  const color = STATUS_COLORS[status];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 10px",
        borderRadius: "var(--radius-xs)",
        fontSize: "0.72rem",
        fontWeight: 600,
        fontFamily: "var(--font-mono)",
        letterSpacing: "0.02em",
        color,
        background: STATUS_SOFT_BG[status],
        border: `1px solid ${color}40`,
      }}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

function AnnotationCard({
  annotation,
  onDelete,
}: {
  annotation: ReviewerAnnotation;
  onDelete: (id: number) => void;
}) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const color = ANNOTATION_TYPE_COLORS[annotation.annotation_type];

  return (
    <div
      style={{
        background: "var(--surface-raised)",
        border: "1px solid var(--border-hairline)",
        borderLeft: `4px solid ${color}`,
        borderRadius: "var(--radius-md)",
        padding: "var(--space-3) var(--space-4)",
        marginBottom: "var(--space-2)",
      }}
    >
      <div
        className="flex items-center justify-between"
        style={{ marginBottom: "var(--space-2)" }}
      >
        <div className="flex items-center gap-2">
          <SharedStatusBadge
            status={ANNOTATION_TYPE_TO_CONCLUSION[annotation.annotation_type]}
          />
          <span className="text-sm" style={{ color: "var(--ink-secondary)" }}>
            {ANNOTATION_TYPE_LABELS[annotation.annotation_type]}
          </span>
          {annotation.target_module && (
            <span className="text-xs" style={{ color: "var(--ink-tertiary)" }}>
              · {TARGET_MODULE_LABELS[annotation.target_module]}
            </span>
          )}
        </div>
        <span
          className="mono text-xs"
          style={{ color: "var(--ink-tertiary)" }}
        >
          {annotation.created_at
            ? new Date(annotation.created_at).toLocaleString("zh-CN")
            : ""}
        </span>
      </div>
      <p
        className="text-sm"
        style={{
          color: "var(--ink-secondary)",
          lineHeight: 1.5,
          margin: "var(--space-1) 0",
        }}
      >
        {annotation.reason}
      </p>
      {annotation.evidence_ids && annotation.evidence_ids.length > 0 && (
        <p
          className="text-xs"
          style={{
            color: "var(--ink-tertiary)",
            margin: "var(--space-1) 0 0",
          }}
        >
          证据 ID:{" "}
          {annotation.evidence_ids.map((eid, i) => (
            <span key={eid} className="mono">
              {i > 0 ? ", " : ""}
              {eid}
            </span>
          ))}
        </p>
      )}
      <div
        className="flex justify-end gap-2"
        style={{ marginTop: "var(--space-2)" }}
      >
        {confirmingDelete ? (
          <>
            <button
              className="btn btn-secondary btn-sm"
              style={{
                color: "var(--negative)",
                borderColor: "var(--negative)",
              }}
              onClick={() => onDelete(annotation.id)}
            >
              确认删除
            </button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setConfirmingDelete(false)}
            >
              取消
            </button>
          </>
        ) : (
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => setConfirmingDelete(true)}
          >
            删除
          </button>
        )}
      </div>
    </div>
  );
}

function CreateAnnotationForm({
  fundCode,
  onCreated,
}: {
  fundCode: string;
  onCreated: () => void;
}) {
  const [annotationType, setAnnotationType] = useState<AnnotationType>("note");
  const [targetModule, setTargetModule] = useState<TargetModule | "">("");
  const [reason, setReason] = useState("");
  const [evidenceId, setEvidenceId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!reason.trim()) {
      setError("请填写原因说明");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const resp = await api.createReviewerAnnotation({
        fund_code: fundCode,
        annotation_type: annotationType,
        target_module: targetModule || null,
        reason: reason.trim(),
        evidence_ids: evidenceId.trim() ? [evidenceId.trim()] : [],
      });
      if (resp.data === null) {
        setError(resp.warnings.join("; ") || "创建失败");
        return;
      }
      setReason("");
      setEvidenceId("");
      setAnnotationType("note");
      setTargetModule("");
      onCreated();
    } catch (e) {
      setError(`创建异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="fade-up fade-up-4"
      style={{
        background: "var(--surface-raised)",
        border: "1px solid var(--border-hairline)",
        borderRadius: "var(--radius-md)",
        padding: "var(--space-4)",
        marginBottom: "var(--space-5)",
      }}
    >
      <SectionHeader title="新增审核记录" subtitle="记录审核决策，影响基金的有效状态" />

      <div
        className="grid"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
          gap: "var(--space-3)",
          marginTop: "var(--space-3)",
        }}
      >
        <label className="form-label">
          <span>类型</span>
          <select
            className="form-input"
            value={annotationType}
            onChange={(e) => setAnnotationType(e.target.value as AnnotationType)}
          >
            {Object.entries(ANNOTATION_TYPE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>

        <label className="form-label">
          <span>目标模块（可选）</span>
          <select
            className="form-input"
            value={targetModule}
            onChange={(e) =>
              setTargetModule(e.target.value as TargetModule | "")
            }
          >
            <option value="">不指定</option>
            {Object.entries(TARGET_MODULE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label
        className="form-label"
        style={{ display: "block", marginTop: "var(--space-3)" }}
      >
        <span>原因说明 *</span>
        <textarea
          className="form-input"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder="说明审核决策的原因，例如：数据质量问题、样本期不足、估计结果不可信..."
          style={{
            width: "100%",
            height: "auto",
            resize: "vertical",
            fontFamily: "var(--font-body)",
            lineHeight: 1.5,
            padding: "var(--space-2) var(--space-3)",
            background: "var(--surface-raised)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--radius-sm)",
            fontSize: "0.82rem",
            color: "var(--ink-primary)",
            boxSizing: "border-box",
          }}
        />
      </label>

      <label
        className="form-label"
        style={{ display: "block", marginTop: "var(--space-3)" }}
      >
        <span>证据 ID（可选）</span>
        <input
          type="text"
          className="form-input"
          value={evidenceId}
          onChange={(e) => setEvidenceId(e.target.value)}
          placeholder="关联的证据记录 ID"
        />
      </label>

      {error && (
        <div
          style={{
            marginTop: "var(--space-3)",
            padding: "var(--space-2) var(--space-3)",
            background: "var(--negative-soft)",
            borderLeft: "3px solid var(--negative)",
            borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
            color: "var(--negative)",
            fontSize: "0.82rem",
          }}
        >
          {error}
        </div>
      )}

      <div style={{ marginTop: "var(--space-4)" }}>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={submitting || !reason.trim()}
        >
          {submitting ? "提交中..." : "提交"}
        </button>
      </div>
    </form>
  );
}

// ---- 证券锁定/排除表单 (POST /review/lock-securities) ----

function LockSecuritiesForm({
  fundCode,
  onCreated,
}: {
  fundCode: string;
  onCreated: () => void;
}) {
  const [securityCode, setSecurityCode] = useState("");
  const [action, setAction] = useState<"lock" | "exclude">("lock");
  const [targetModule, setTargetModule] = useState<TargetModule>("simulated_holding");
  const [lockWeight, setLockWeight] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!securityCode.trim()) {
      setError("请填写证券代码");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const resp = await api.lockSecurities({
        fund_code: fundCode,
        security_code: securityCode.trim(),
        action,
        target_module: targetModule,
        reason: reason.trim() || undefined,
        lock_weight: lockWeight.trim() ? parseFloat(lockWeight) : null,
      });
      if (resp.data === null) {
        setError(resp.warnings.join("; ") || "操作失败");
        return;
      }
      setSecurityCode("");
      setLockWeight("");
      setReason("");
      onCreated();
    } catch (e) {
      setError(`操作异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="fade-up fade-up-4"
      style={{
        background: "var(--surface-raised)",
        border: "1px solid var(--border-hairline)",
        borderRadius: "var(--radius-md)",
        padding: "var(--space-4)",
        marginBottom: "var(--space-5)",
      }}
    >
      <SectionHeader title="证券锁定/排除" subtitle="强制包含或排除特定证券（影响模拟持仓）" />
      <div
        className="grid"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
          gap: "var(--space-3)",
          marginTop: "var(--space-3)",
        }}
      >
        <label className="form-label">
          <span>证券代码 *</span>
          <input
            type="text"
            className="form-input"
            value={securityCode}
            onChange={(e) => setSecurityCode(e.target.value)}
            placeholder="如 600519"
          />
        </label>
        <label className="form-label">
          <span>操作</span>
          <select
            className="form-input"
            value={action}
            onChange={(e) => setAction(e.target.value as "lock" | "exclude")}
          >
            <option value="lock">锁定（强制包含）</option>
            <option value="exclude">排除（强制剔除）</option>
          </select>
        </label>
        <label className="form-label">
          <span>目标模块</span>
          <select
            className="form-input"
            value={targetModule}
            onChange={(e) => setTargetModule(e.target.value as TargetModule)}
          >
            {Object.entries(TARGET_MODULE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="form-label">
          <span>锁定权重（可选）</span>
          <input
            type="number"
            className="form-input"
            value={lockWeight}
            onChange={(e) => setLockWeight(e.target.value)}
            placeholder="0.0 ~ 1.0"
            min="0"
            max="1"
            step="0.01"
          />
        </label>
      </div>
      <label className="form-label" style={{ display: "block", marginTop: "var(--space-3)" }}>
        <span>原因说明</span>
        <input
          type="text"
          className="form-input"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="说明锁定/排除的原因"
        />
      </label>
      {error && (
        <div style={{ marginTop: "var(--space-3)", color: "var(--negative)", fontSize: "0.82rem" }}>
          {error}
        </div>
      )}
      <div style={{ marginTop: "var(--space-4)" }}>
        <button type="submit" className="btn btn-primary" disabled={submitting || !securityCode.trim()}>
          {submitting ? "提交中..." : "提交"}
        </button>
      </div>
    </form>
  );
}

// ---- 基准调整表单 (POST /review/adjust-benchmark) ----

function AdjustBenchmarkForm({
  fundCode,
  onCreated,
}: {
  fundCode: string;
  onCreated: () => void;
}) {
  const [benchmarkSymbol, setBenchmarkSymbol] = useState("");
  const [customWeights, setCustomWeights] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!benchmarkSymbol.trim()) {
      setError("请填写基准代码");
      return;
    }
    let weightsParsed: Record<string, number> | null = null;
    if (customWeights.trim()) {
      try {
        weightsParsed = JSON.parse(customWeights);
      } catch {
        setError("自定义权重要求 JSON 格式，如 {\"行业1\": 0.3}");
        return;
      }
    }
    setSubmitting(true);
    setError(null);
    try {
      const resp = await api.adjustBenchmark({
        fund_code: fundCode,
        benchmark_symbol: benchmarkSymbol.trim(),
        custom_weights: weightsParsed,
        reason: reason.trim() || undefined,
      });
      if (resp.data === null) {
        setError(resp.warnings.join("; ") || "操作失败");
        return;
      }
      setBenchmarkSymbol("");
      setCustomWeights("");
      setReason("");
      onCreated();
    } catch (e) {
      setError(`操作异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="fade-up fade-up-4"
      style={{
        background: "var(--surface-raised)",
        border: "1px solid var(--border-hairline)",
        borderRadius: "var(--radius-md)",
        padding: "var(--space-4)",
        marginBottom: "var(--space-5)",
      }}
    >
      <SectionHeader title="基准调整" subtitle="覆盖默认基准代码和行业权重（影响动态归因）" />
      <div
        className="grid"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
          gap: "var(--space-3)",
          marginTop: "var(--space-3)",
        }}
      >
        <label className="form-label">
          <span>基准代码 *</span>
          <input
            type="text"
            className="form-input"
            value={benchmarkSymbol}
            onChange={(e) => setBenchmarkSymbol(e.target.value)}
            placeholder="如 sh000300"
          />
        </label>
      </div>
      <label className="form-label" style={{ display: "block", marginTop: "var(--space-3)" }}>
        <span>自定义行业权重（可选 JSON）</span>
        <input
          type="text"
          className="form-input"
          value={customWeights}
          onChange={(e) => setCustomWeights(e.target.value)}
          placeholder='如 {"制造业": 0.4, "金融业": 0.3}'
        />
      </label>
      <label className="form-label" style={{ display: "block", marginTop: "var(--space-3)" }}>
        <span>原因说明</span>
        <input
          type="text"
          className="form-input"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="说明调整基准的原因"
        />
      </label>
      {error && (
        <div style={{ marginTop: "var(--space-3)", color: "var(--negative)", fontSize: "0.82rem" }}>
          {error}
        </div>
      )}
      <div style={{ marginTop: "var(--space-4)" }}>
        <button type="submit" className="btn btn-primary" disabled={submitting || !benchmarkSymbol.trim()}>
          {submitting ? "提交中..." : "提交"}
        </button>
      </div>
    </form>
  );
}

// ---- 置信度标注表单 (POST /review/annotate-confidence) ----

function AnnotateConfidenceForm({
  fundCode,
  onCreated,
}: {
  fundCode: string;
  onCreated: () => void;
}) {
  const [targetModule, setTargetModule] = useState<TargetModule>("scoring");
  const [adjustedStatus, setAdjustedStatus] = useState<
    "fact" | "computed" | "estimated" | "observation" | "needs_review"
  >("needs_review");
  const [originalStatus, setOriginalStatus] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const STATUS_LABELS: Record<string, string> = {
    fact: "事实 (fact)",
    computed: "计算 (computed)",
    estimated: "估算 (estimated)",
    observation: "观察 (observation)",
    needs_review: "待复核 (needs_review)",
  };

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!reason.trim()) {
      setError("请填写原因说明");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const resp = await api.annotateConfidence({
        fund_code: fundCode,
        target_module: targetModule,
        adjusted_status: adjustedStatus,
        original_status: originalStatus.trim() || null,
        reason: reason.trim(),
      });
      if (resp.data === null) {
        setError(resp.warnings.join("; ") || "操作失败");
        return;
      }
      setReason("");
      setOriginalStatus("");
      onCreated();
    } catch (e) {
      setError(`操作异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="fade-up fade-up-4"
      style={{
        background: "var(--surface-raised)",
        border: "1px solid var(--border-hairline)",
        borderRadius: "var(--radius-md)",
        padding: "var(--space-4)",
        marginBottom: "var(--space-5)",
      }}
    >
      <SectionHeader title="置信度标注" subtitle="手动调整算法结果的结论状态等级" />
      <div
        className="grid"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
          gap: "var(--space-3)",
          marginTop: "var(--space-3)",
        }}
      >
        <label className="form-label">
          <span>目标模块 *</span>
          <select
            className="form-input"
            value={targetModule}
            onChange={(e) => setTargetModule(e.target.value as TargetModule)}
          >
            {Object.entries(TARGET_MODULE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="form-label">
          <span>调整后状态 *</span>
          <select
            className="form-input"
            value={adjustedStatus}
            onChange={(e) =>
              setAdjustedStatus(
                e.target.value as
                  | "fact"
                  | "computed"
                  | "estimated"
                  | "observation"
                  | "needs_review"
              )
            }
          >
            {Object.entries(STATUS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="form-label">
          <span>原始状态（可选）</span>
          <input
            type="text"
            className="form-input"
            value={originalStatus}
            onChange={(e) => setOriginalStatus(e.target.value)}
            placeholder="如 estimated"
          />
        </label>
      </div>
      <label className="form-label" style={{ display: "block", marginTop: "var(--space-3)" }}>
        <span>原因说明 *</span>
        <textarea
          className="form-input"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          placeholder="说明调整置信度的原因"
          style={{ width: "100%", height: "auto", resize: "vertical" }}
        />
      </label>
      {error && (
        <div style={{ marginTop: "var(--space-3)", color: "var(--negative)", fontSize: "0.82rem" }}>
          {error}
        </div>
      )}
      <div style={{ marginTop: "var(--space-4)" }}>
        <button type="submit" className="btn btn-primary" disabled={submitting || !reason.trim()}>
          {submitting ? "提交中..." : "提交"}
        </button>
      </div>
    </form>
  );
}

export default function FundReviewPage() {
  const { code } = useParams<{ code: string }>();
  const fundCode = code || "";

  const [status, setStatus] = useState<EffectiveStatus | null>(null);
  const [annotations, setAnnotations] = useState<ReviewerAnnotation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!fundCode) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await api.getFundReviewStatus(fundCode);
      if (resp.data === null) {
        setError(resp.warnings.join("; ") || "查询失败");
        return;
      }
      setStatus(resp.data.effective_status);
      setAnnotations(resp.data.annotations);
    } catch (e) {
      setError(`加载异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [fundCode]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  async function handleDelete(id: number) {
    try {
      const resp = await api.deleteReviewerAnnotation(id);
      if (resp.data === null) {
        setError(resp.warnings.join("; ") || "删除失败");
        return;
      }
      await loadData();
    } catch (e) {
      setError(`删除异常: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  const crumbs: BreadcrumbItem[] = [
    { label: "基金筛选", to: "/funds" },
    { label: fundCode, to: `/funds/${fundCode}` },
    { label: "手动校验" },
  ];

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center gap-3">
          <h1>手动校验</h1>
          <span
            className="mono text-sm"
            style={{ color: "var(--ink-tertiary)" }}
          >
            {fundCode}
          </span>
          {status && <ReviewStatusBadge status={status} />}
        </div>
      </div>

      {loading ? (
        <div className="fade-up fade-up-2">
          <LoadingState rows={4} cols={4} />
        </div>
      ) : status === null && error ? (
        <div className="fade-up fade-up-2">
          <ErrorState
            title="加载失败"
            desc={error}
            onRetry={() => {
              setError(null);
              loadData();
            }}
          />
        </div>
      ) : (
        <>
          {/* 非致命错误提示 */}
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
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => setError(null)}
                >
                  关闭
                </button>
              </div>
            </div>
          )}

          {/* 汇总指标卡 */}
          <div
            className="grid grid-2 fade-up fade-up-2 mb-6"
            style={{ gap: "var(--space-4)" }}
          >
            <div
              style={{
                background: "var(--surface-raised)",
                border: "1px solid var(--border-hairline)",
                borderRadius: "var(--radius-md)",
                padding: "var(--space-4)",
              }}
            >
              <MetricCard label="审核记录数" value={annotations.length} />
            </div>
            <div
              style={{
                background: "var(--surface-raised)",
                border: "1px solid var(--border-hairline)",
                borderRadius: "var(--radius-md)",
                padding: "var(--space-4)",
              }}
            >
              <MetricCard
                label="有效状态"
                value={status ? STATUS_LABELS[status] : "—"}
              />
            </div>
          </div>

          {/* 状态警告横幅 */}
          {status === "excluded" && (
            <div
              className="fade-up fade-up-3 mb-4"
              style={{
                padding: "var(--space-3) var(--space-4)",
                background: "var(--negative-soft)",
                borderLeft: "3px solid var(--negative)",
                borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
                color: "var(--negative)",
                fontSize: "0.85rem",
              }}
            >
              该基金已被标记为"排除"，不会出现在默认结论和排名中。
            </div>
          )}
          {status === "locked" && (
            <div
              className="fade-up fade-up-3 mb-4"
              style={{
                padding: "var(--space-3) var(--space-4)",
                background: "var(--warning-soft)",
                borderLeft: "3px solid var(--warning)",
                borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
                color: "var(--warning)",
                fontSize: "0.85rem",
              }}
            >
              该基金已被锁定，重新运行算法不会覆盖当前结果。
            </div>
          )}

          {/* 新增审核记录表单 */}
          <CreateAnnotationForm fundCode={fundCode} onCreated={loadData} />

          {/* 业务级审核操作 */}
          <LockSecuritiesForm fundCode={fundCode} onCreated={loadData} />
          <AdjustBenchmarkForm fundCode={fundCode} onCreated={loadData} />
          <AnnotateConfidenceForm fundCode={fundCode} onCreated={loadData} />

          {/* 审核记录历史 */}
          <div className="fade-up fade-up-5">
            <SectionHeader
              title="审核记录历史"
              subtitle={`共 ${annotations.length} 条记录`}
            />
            {annotations.length === 0 ? (
              <EmptyState
                icon="∅"
                title="暂无审核记录"
                desc="通过上方表单添加第一条审核记录"
              />
            ) : (
              <div>
                {annotations.map((a) => (
                  <AnnotationCard
                    key={a.id}
                    annotation={a}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
