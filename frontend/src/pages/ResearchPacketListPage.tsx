// 研究包归档列表 — 浏览已保存的 Research Packet 记录
// 支持按基金代码过滤 + 分页；点击行跳转详情页

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type ResearchPacketListItem } from "../api/client";
import { DataTable, type Column } from "../components/data/DataTable";
import {
  Breadcrumb,
  MetricCard,
  StatusBadge,
  LoadingState,
  EmptyState,
  ErrorState,
  type BreadcrumbItem,
} from "../components/display";

const TEMPLATE_LABELS: Record<string, string> = {
  single_fund_checkup: "单基金体检",
  manager_profile: "经理画像",
  style_drift: "风格漂移",
  holdings_deep_dive: "持仓深析",
};

const CONFIDENCE_STATUS: Record<string, string> = {
  computed: "computed",
  estimated: "estimated",
  needs_review: "needs_review",
  high: "computed",
  medium: "estimated",
  low: "needs_review",
};

function formatDate(v: string | null): string {
  if (!v) return "—";
  // generated_at 是 ISO datetime，data_date 是 date
  return v.length > 10 ? v.slice(0, 16).replace("T", " ") : v;
}

export default function ResearchPacketListPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<ResearchPacketListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fundCode, setFundCode] = useState("");
  const [limit, setLimit] = useState(20);

  async function load(code?: string) {
    setLoading(true);
    setError(null);
    try {
      const body = await api.listResearchPackets({
        fund_code: code || undefined,
        limit,
      });
      if (body.data === null) {
        setError(body.warnings.join("; ") || "加载失败");
        setItems([]);
        return;
      }
      setItems(body.data?.packets ?? []);
    } catch (e) {
      setError(`加载异常: ${e instanceof Error ? e.message : String(e)}`);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onSubmitFilter(e: React.FormEvent) {
    e.preventDefault();
    load(fundCode.trim());
  }

  const latestCount = items.filter((it) => it.is_latest).length;
  const needsReviewCount = items.filter(
    (it) => it.overall_confidence === "needs_review" || it.overall_confidence === "low",
  ).length;

  const crumbs: BreadcrumbItem[] = [{ label: "研究包归档" }];

  const columns: Column<ResearchPacketListItem>[] = [
    {
      key: "packet_id",
      header: "Packet ID",
      sortable: true,
      sortValue: (r) => r.packet_id,
      render: (r) => (
        <span className="mono text-xs" title={r.packet_id}>
          {r.packet_id.length > 16
            ? `${r.packet_id.slice(0, 8)}…${r.packet_id.slice(-4)}`
            : r.packet_id}
        </span>
      ),
      width: "140px",
    },
    {
      key: "fund_code",
      header: "基金代码",
      sortable: true,
      sortValue: (r) => r.fund_code,
      render: (r) => <span className="mono font-medium">{r.fund_code}</span>,
      width: "110px",
    },
    {
      key: "template",
      header: "模板",
      sortable: true,
      sortValue: (r) => r.template,
      render: (r) => (
        <span>{TEMPLATE_LABELS[r.template] ?? r.template}</span>
      ),
    },
    {
      key: "data_date",
      header: "数据日期",
      sortable: true,
      sortValue: (r) => r.data_date ?? "",
      render: (r) => (
        <span className="mono text-sm">{r.data_date ?? "—"}</span>
      ),
      width: "110px",
    },
    {
      key: "generated_at",
      header: "生成时间",
      sortable: true,
      sortValue: (r) => r.generated_at ?? "",
      render: (r) => (
        <span className="mono text-sm">{formatDate(r.generated_at)}</span>
      ),
    },
    {
      key: "overall_confidence",
      header: "置信度",
      sortable: true,
      sortValue: (r) => r.overall_confidence ?? "",
      render: (r) => (
        <StatusBadge
          status={CONFIDENCE_STATUS[r.overall_confidence ?? ""] ?? "observation"}
        />
      ),
      width: "100px",
    },
    {
      key: "is_latest",
      header: "最新",
      sortable: true,
      sortValue: (r) => (r.is_latest ? "1" : "0"),
      render: (r) =>
        r.is_latest ? (
          <span
            className="text-xs"
            style={{
              padding: "2px 8px",
              borderRadius: "var(--radius-xs)",
              background: "var(--positive-soft)",
              color: "var(--positive)",
              fontWeight: 500,
            }}
          >
            最新
          </span>
        ) : (
          <span className="text-tertiary text-xs">—</span>
        ),
      width: "70px",
    },
  ];

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1 mb-4">
        <h1>研究包归档</h1>
        <div className="text-sm text-tertiary mt-2">
          浏览已生成并持久化的 Research Packet 记录（v2 端点）
        </div>
      </div>

      {/* 汇总指标卡 */}
      <div className="grid grid-4 fade-up fade-up-2 mb-6">
        <MetricCard label="记录总数" value={items.length} />
        <MetricCard label="最新版本" value={latestCount} positive={latestCount > 0} />
        <MetricCard
          label="待复核"
          value={needsReviewCount}
          negative={needsReviewCount > 0}
        />
        <MetricCard label="分页上限" value={limit} />
      </div>

      {/* 过滤栏 */}
      <form
        onSubmit={onSubmitFilter}
        className="fade-up fade-up-2 mb-4"
        style={{
          background: "var(--surface-raised)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-3) var(--space-4)",
          border: "1px solid var(--border-hairline)",
        }}
      >
        <div
          className="grid"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
            gap: "var(--space-3)",
            alignItems: "end",
          }}
        >
          <label className="form-label">
            <span>基金代码（可选）</span>
            <input
              className="form-input"
              value={fundCode}
              onChange={(e) => setFundCode(e.target.value)}
              placeholder="如 000001"
            />
          </label>
          <label className="form-label">
            <span>分页数量</span>
            <select
              className="form-input"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </label>
          <div className="flex items-center gap-2">
            <button type="submit" className="btn btn-primary btn-sm">
              查询
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setFundCode("");
                setLimit(20);
                load();
              }}
            >
              重置
            </button>
          </div>
        </div>
      </form>

      {/* 错误提示 */}
      {error && (
        <div className="fade-up fade-up-3 mb-4">
          <ErrorState title="加载失败" desc={error} />
        </div>
      )}

      {/* 列表 */}
      <div className="fade-up fade-up-3">
        {loading ? (
          <LoadingState rows={6} cols={6} />
        ) : items.length === 0 ? (
          <EmptyState
            icon="∅"
            title="暂无研究包记录"
            desc="在基金详情页的「研究输出」标签下生成研究包后，记录会出现在这里"
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
              data={items}
              rowKey={(r) => r.packet_id}
              onRowClick={(r) => navigate(`/research-packets/${r.packet_id}`)}
              initialSort={{ key: "generated_at", order: "desc" }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
