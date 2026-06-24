import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  api,
  type AnnotationType,
  type EffectiveStatus,
  type ReviewerAnnotation,
  type TargetModule,
} from "../api/client";

const ANNOTATION_TYPE_LABELS: Record<AnnotationType, string> = {
  note: "备注",
  lock: "锁定",
  exclude: "排除",
  approve: "批准",
};

const ANNOTATION_TYPE_COLORS: Record<AnnotationType, string> = {
  note: "var(--color-text-secondary)",
  lock: "var(--color-warning)",
  exclude: "var(--color-danger)",
  approve: "var(--color-success)",
};

const TARGET_MODULE_LABELS: Record<TargetModule, string> = {
  scoring: "综合评分",
  simulated_holding: "模拟持仓",
  dynamic_attribution: "动态归因",
};

const STATUS_COLORS: Record<EffectiveStatus, string> = {
  open: "var(--color-text-secondary)",
  approved: "var(--color-success)",
  locked: "var(--color-warning)",
  excluded: "var(--color-danger)",
};

const STATUS_LABELS: Record<EffectiveStatus, string> = {
  open: "待审核",
  approved: "已批准",
  locked: "已锁定",
  excluded: "已排除",
};

function StatusBadge({ status }: { status: EffectiveStatus }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 10px",
        borderRadius: 12,
        fontSize: 12,
        fontWeight: 600,
        color: STATUS_COLORS[status],
        background: `${STATUS_COLORS[status]}20`,
        border: `1px solid ${STATUS_COLORS[status]}40`,
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
        border: "1px solid var(--color-border)",
        borderRadius: 8,
        padding: 12,
        marginBottom: 8,
        borderLeft: `4px solid ${color}`,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: 6,
        }}
      >
        <div>
          <span
            style={{
              fontWeight: 600,
              color,
              fontSize: 13,
            }}
          >
            {ANNOTATION_TYPE_LABELS[annotation.annotation_type]}
          </span>
          {annotation.target_module && (
            <span
              style={{
                marginLeft: 8,
                fontSize: 12,
                color: "var(--color-text-secondary)",
              }}
            >
              {TARGET_MODULE_LABELS[annotation.target_module]}
            </span>
          )}
        </div>
        <span style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>
          {annotation.created_at
            ? new Date(annotation.created_at).toLocaleString("zh-CN")
            : ""}
        </span>
      </div>
      <p style={{ margin: "4px 0", fontSize: 13, lineHeight: 1.5 }}>
        {annotation.reason}
      </p>
      {annotation.evidence_id && (
        <p style={{ margin: "4px 0", fontSize: 11, color: "var(--color-text-secondary)" }}>
          证据 ID: {annotation.evidence_id}
        </p>
      )}
      <div style={{ marginTop: 8, textAlign: "right" }}>
        {confirmingDelete ? (
          <>
            <button
              className="btn btn-danger btn-sm"
              onClick={() => onDelete(annotation.id)}
            >
              确认删除
            </button>
            <button
              className="btn btn-sm"
              style={{ marginLeft: 4 }}
              onClick={() => setConfirmingDelete(false)}
            >
              取消
            </button>
          </>
        ) : (
          <button
            className="btn btn-sm"
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
        evidence_id: evidenceId.trim() || null,
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
      style={{
        border: "1px solid var(--color-border)",
        borderRadius: 8,
        padding: 16,
        marginBottom: 16,
      }}
    >
      <h3 style={{ marginTop: 0, marginBottom: 12, fontSize: 15 }}>
        新增审核记录
      </h3>

      <div style={{ display: "flex", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            类型
          </span>
          <select
            value={annotationType}
            onChange={(e) => setAnnotationType(e.target.value as AnnotationType)}
            style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid var(--color-border)" }}
          >
            {Object.entries(ANNOTATION_TYPE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>

        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            目标模块（可选）
          </span>
          <select
            value={targetModule}
            onChange={(e) => setTargetModule(e.target.value as TargetModule | "")}
            style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid var(--color-border)" }}
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

      <label style={{ display: "block", marginBottom: 12 }}>
        <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
          原因说明 *
        </span>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder="说明审核决策的原因，例如：数据质量问题、样本期不足、估计结果不可信..."
          style={{
            width: "100%",
            padding: "6px 8px",
            borderRadius: 4,
            border: "1px solid var(--color-border)",
            boxSizing: "border-box",
            fontFamily: "inherit",
            fontSize: 13,
          }}
        />
      </label>

      <label style={{ display: "block", marginBottom: 12 }}>
        <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
          证据 ID（可选）
        </span>
        <input
          type="text"
          value={evidenceId}
          onChange={(e) => setEvidenceId(e.target.value)}
          placeholder="关联的证据记录 ID"
          style={{
            width: "100%",
            padding: "4px 8px",
            borderRadius: 4,
            border: "1px solid var(--color-border)",
            boxSizing: "border-box",
            fontFamily: "inherit",
            fontSize: 13,
          }}
        />
      </label>

      {error && (
        <div
          style={{
            color: "var(--color-danger)",
            fontSize: 12,
            marginBottom: 8,
          }}
        >
          {error}
        </div>
      )}

      <button
        type="submit"
        className="btn btn-primary"
        disabled={submitting || !reason.trim()}
      >
        {submitting ? "提交中..." : "提交"}
      </button>
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

  return (
    <div>
      <h2 style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span>手动校验 — {fundCode}</span>
        {status && <StatusBadge status={status} />}
      </h2>

      {error && (
        <div
          className="warning-banner"
          style={{ marginBottom: 16 }}
        >
          {error}
        </div>
      )}

      {loading ? (
        <p style={{ color: "var(--color-text-secondary)" }}>加载中...</p>
      ) : (
        <>
          <div
            style={{
              display: "flex",
              gap: 16,
              marginBottom: 16,
              flexWrap: "wrap",
            }}
          >
            <div className="metric-card">
              <div className="metric-card-label">审核记录数</div>
              <div className="metric-card-value">{annotations.length}</div>
            </div>
            <div className="metric-card">
              <div className="metric-card-label">有效状态</div>
              <div className="metric-card-value">
                {status ? STATUS_LABELS[status] : "—"}
              </div>
            </div>
          </div>

          {status === "excluded" && (
            <div
              className="warning-banner"
              style={{ marginBottom: 16 }}
            >
              该基金已被标记为"排除"，不会出现在默认结论和排名中。
            </div>
          )}
          {status === "locked" && (
            <div
              className="warning-banner"
              style={{ marginBottom: 16 }}
            >
              该基金已被锁定，重新运行算法不会覆盖当前结果。
            </div>
          )}

          <CreateAnnotationForm
            fundCode={fundCode}
            onCreated={loadData}
          />

          <h3 style={{ fontSize: 15, marginBottom: 8 }}>
            审核记录历史
          </h3>
          {annotations.length === 0 ? (
            <p style={{ color: "var(--color-text-secondary)" }}>
              暂无审核记录
            </p>
          ) : (
            annotations.map((a) => (
              <AnnotationCard
                key={a.id}
                annotation={a}
                onDelete={handleDelete}
              />
            ))
          )}
        </>
      )}
    </div>
  );
}
