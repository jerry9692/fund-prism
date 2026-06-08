/**
 * API client — single source of truth for all backend communication.
 * Switch backend URL by changing BASE_URL only.
 */

const BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

// ---- Types (shared across all pages) ----

export interface APIResponse<T = unknown> {
  data: T | null;
  metadata: Record<string, unknown>;
  evidence: EvidenceRecord[];
  warnings: string[];
  conclusion_status: string;
  not_applicable_reason: string | null;
}

export interface EvidenceRecord {
  evidence_id: string;
  entity_id: string;
  evidence_type: string;
  source: string;
  source_level: string;
  date_range: [string, string] | null;
  data_summary: string | null;
  confidence: string;
  conclusion_status: string;
}

export interface FundProfile {
  fund_code: string;
  short_name: string;
  full_name: string;
  category: string;
  sub_category: string | null;
  inception_date: string | null;
  company_name: string;
  custodian_bank: string | null;
  status: string;
  benchmark: string | null;
  managers: ManagerInfo[];
  scale_history: ScaleRecord[];
  fee_info: FeeInfo | null;
}

export interface ManagerInfo {
  name: string;
  start_date: string | null;
  tenure_days: number;
  is_current: boolean;
}

export interface ScaleRecord {
  report_date: string;
  total_nav: number;
}

export interface FeeInfo {
  mgmt_fee_pct: number;
  custody_fee_pct: number | null;
  sales_service_fee_pct: number | null;
}

export interface NavPeriod {
  label: string;
  status: string;
  metrics: Record<string, number | null> | null;
  observations: number;
  start_date: string | null;
  end_date: string | null;
  warnings: string[];
}

export interface NavMetricsData {
  fund_code: string;
  periods: Record<string, NavPeriod>;
  custom: NavPeriod | null;
}

export interface HoldingItem {
  asset_type: string;
  security_code: string;
  security_name: string;
  weight_pct: number;
  market_value: number | null;
  rank_in_holdings: number | null;
  industry: string | null;
  change_direction: string | null;
}

export interface HoldingsData {
  report_date: string | null;
  disclosure_granularity: string;
  holdings: HoldingItem[];
  total_weight_pct: number | null;
  concentration_top10_pct: number | null;
  industry_distribution: { name: string; weight_pct: number }[];
  holding_changes: Record<string, unknown>[];
  change_summary: Record<string, number>;
}

export interface ExposureData {
  exposure_values: Record<string, number>;
  residual: number | null;
  r_squared: number | null;
  observations: number;
  static_attribution: {
    report_date: string | null;
    total_return: number | null;
    explained_return: number | null;
    residual: number | null;
    residual_pct: number | null;
    coverage_rate: number;
    security_contributions: Record<string, unknown>[];
    industry_contributions: Record<string, unknown>[];
  } | null;
}

export interface DiffData {
  fund_code: string;
  left_info: { packet_id: string; data_date: string };
  right_info: { packet_id: string; data_date: string };
  changed: boolean;
  diffs: Record<string, unknown>;
}

export interface ScreenFilters {
  category?: string;
  min_inception_years?: number;
  min_scale_bn?: number;
  max_scale_bn?: number;
  min_manager_tenure_days?: number;
  max_mgmt_fee_pct?: number;
}

export interface ScreenResult {
  funds: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
}

// ---- Generic fetch wrapper ----

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<APIResponse<T>> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<APIResponse<T>>;
}

// ---- API functions (one per endpoint) ----

export const api = {
  health: () => request<{ status: string }>("/api/v1/health"),

  getFundProfile: (code: string) =>
    request<FundProfile>(`/api/v1/funds/${code}/profile`),

  getNavMetrics: (code: string, params?: { start?: string; end?: string }) => {
    const search = params
      ? "?" + new URLSearchParams(params as Record<string, string>).toString()
      : "";
    return request<NavMetricsData>(`/api/v1/funds/${code}/nav-metrics${search}`);
  },

  getHoldings: (code: string, params?: { report_date?: string }) => {
    const search = params
      ? "?" + new URLSearchParams(params as Record<string, string>).toString()
      : "";
    return request<HoldingsData>(`/api/v1/funds/${code}/holdings${search}`);
  },

  getExposure: (code: string, window = 60) =>
    request<ExposureData>(
      `/api/v1/analysis/exposure?fund_code=${code}&window=${window}`
    ),

  getResearchPacket: (code: string, template = "single_fund_checkup") =>
    request<{ packet_id: string; packet: Record<string, unknown> }>(
      `/api/v1/research/packet?fund_code=${code}&template=${template}`
    ),

  diffPackets: (body: Record<string, unknown>) =>
    request<DiffData>("/api/v1/research/diff", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  screenFunds: (body: {
    filters?: ScreenFilters;
    sort_by?: string;
    sort_order?: string;
    limit?: number;
    offset?: number;
  }) =>
    request<ScreenResult>("/api/v1/funds/screen", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
