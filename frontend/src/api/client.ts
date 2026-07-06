/**
 * API client — single source of truth for all backend communication.
 * Switch backend URL by changing BASE_URL only.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

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

export interface NavSeriesData {
  fund_code: string;
  start_date: string;
  end_date: string;
  dates: string[];
  unit_nav: (number | null)[];
  accumulated_nav: (number | null)[];
  normalized_nav: (number | null)[];
  daily_return: (number | null)[];
  benchmark_code: string | null;
  benchmark_dates: string[];
  benchmark_normalized_nav: (number | null)[];
  total_points: number;
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

// R4: 已保存的研究包列表/详情（v2）
export interface ResearchPacketListItem {
  packet_id: string;
  fund_code: string;
  template: string;
  generated_at: string | null;
  data_date: string | null;
  platform_version: string | null;
  overall_confidence: string | null;
  is_latest: boolean | null;
}

export interface ResearchPacketDetail extends ResearchPacketListItem {
  packet: Record<string, unknown>;
  markdown: string | null;
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

export interface Experiment {
  id: string;
  name: string;
  algorithm: string;
  version: string;
  status: string;
  fund_count: number;
  success_count: number;
  failure_count: number;
  created_at: string;
}

export interface ExperimentResultItem {
  fund_code: string;
  is_success: boolean;
  metrics: Record<string, unknown> | null;
  error_message: string | null;
  warnings?: string[] | null;
}

export interface ExperimentDetail {
  id: string;
  experiment_name: string;
  algorithm_name: string;
  algorithm_version: string;
  status: string;
  results: ExperimentResultItem[];
  summary?: string;
}

export interface ExperimentListData {
  experiments: Experiment[];
  total: number;
}

export interface P2BAlgorithmReport {
  experiment_summary: {
    fund_count: number;
    success_count: number;
    failure_count: number;
    algorithm_name?: string;
    status?: string;
  };
  aggregate_stats: Record<string, number | null>;
  per_fund: Array<{
    fund_code: string;
    is_success: boolean;
    diagnostics?: Record<string, unknown>;
    metrics?: Record<string, unknown>;
    error_message: string | null;
    warnings: string[];
  }>;
  overall_conclusion: string;
  conclusion_status: string;
  warnings: string[];
}

export interface P2BValidationReport {
  report_type: string;
  report_id?: string;
  generated_at: string;
  generated_date?: string;
  expected_fund_count: number;
  sample_fund_count: number;
  pipeline_gate: { status: string; conclusion_status?: string };
  productization_gate: { status: string; conclusion_status?: string; warnings?: string[] };
  readiness_summary: Record<string, {
    level: string;
    productization_allowed: boolean;
    reason: string;
  }>;
  gate_checks: Array<{ name: string; passed: boolean; detail: string }>;
  algorithms: Record<string, P2BAlgorithmReport>;
  warnings: string[];
  conclusion_status: string;
}

export interface P2BValidationReportSummary {
  report_id: string;
  generated_at: string | null;
  sample_fund_count: number | null;
  expected_fund_count: number | null;
  pipeline_status: string | null;
  productization_status: string | null;
  conclusion_status: string | null;
  algorithm_count: number;
  warning_count: number;
  is_latest: boolean;
}

export interface P2BValidationReportListData {
  reports: P2BValidationReportSummary[];
  total: number;
}

export interface P2BValidationComparison {
  base: P2BValidationReportSummary;
  target: P2BValidationReportSummary;
  changed: boolean;
  gate_changes: Array<{
    name: string;
    base_passed: boolean | null;
    target_passed: boolean | null;
    base_detail: string | null;
    target_detail: string | null;
    changed: boolean;
  }>;
  algorithm_changes: Array<{
    algorithm: string;
    base_conclusion: string | null;
    target_conclusion: string | null;
    base_readiness: string | null;
    target_readiness: string | null;
    base_success_count: number | null;
    target_success_count: number | null;
    base_failure_count: number | null;
    target_failure_count: number | null;
    metric_deltas: Record<string, {
      base: number | null;
      target: number | null;
      delta: number | null;
    }>;
    changed: boolean;
  }>;
}

export interface P2BValidationTask {
  task_id: string;
  status: "queued" | "running" | "completed" | "failed" | string;
  stage: string;
  message: string | null;
  percent: number | null;
  current?: number | null;
  total?: number | null;
  algorithm?: string | null;
  algorithms?: string[];
  limit?: number | null;
  report_id?: string | null;
  generated_at?: string | null;
  report_path?: string | null;
  history_path?: string | null;
  warnings?: string[];
}

export interface FundScoreItem {
  fund_code: string;
  total_score: number;
  sub_scores: Record<string, number>;
  percentile_rank: number;
  deduction_reasons: string[];
  contains_estimated: boolean;
  conclusion_status?: string;
  warnings?: string[];
  calc_date?: string | null;
}

export interface ScoringData {
  score_version: string;
  fund_count: number;
  success_count: number;
  fund_scores: FundScoreItem[];
  experiment_id?: string;
}

export interface ScoringVersionData {
  score_version: string;
  fund_count: number;
  fund_scores: FundScoreItem[];
}

export interface ScoringBacktestItem {
  id: number;
  score_version: string;
  backtest_date: string | null;
  group_count: number;
  ic_mean: number | null;
  ic_ir: number | null;
  monotonicity_check: boolean | null;
  created_at: string | null;
}

export interface ScoringBacktestDetail extends ScoringBacktestItem {
  group_results: Record<string, Record<string, number>> | null;
  detail: {
    ic_count?: number;
    warnings?: unknown[];
    eval_date_count?: number;
    forward_months?: number;
    min_forward_observations?: number;
    monotonicity_checks?: Record<string, boolean>;
  } | null;
}

// ---- Reviewer Annotation types ----

export type AnnotationType =
  | "note"
  | "lock"
  | "exclude"
  | "approve"
  | "flag"
  | "benchmark_override"
  | "confidence_override";
export type TargetModule = "scoring" | "simulated_holding" | "dynamic_attribution";
export type EffectiveStatus = "excluded" | "locked" | "approved" | "open";

export interface ReviewerAnnotation {
  id: number;
  fund_code: string;
  annotation_type: AnnotationType;
  target_module: TargetModule | null;
  detail: Record<string, unknown>;
  reason: string;
  evidence_ids: string[] | null;
  created_at: string | null;
}

export interface ReviewerAnnotationListData {
  annotations: ReviewerAnnotation[];
  count: number;
}

export interface FundReviewStatus {
  fund_code: string;
  annotation_count: number;
  is_locked: boolean;
  is_excluded: boolean;
  is_approved: boolean;
  effective_status: EffectiveStatus;
  annotations: ReviewerAnnotation[];
}

// ---- Simulated Holding types ----

export interface SimulatedHoldingItem {
  stock_code: string;
  stock_name: string | null;
  estimated_weight: number;
  industry: string | null;
  confidence: string | null;
}

export interface SimulatedHoldingResult {
  id: number;
  fund_code: string;
  calc_date: string | null;
  algorithm_name: string;
  algorithm_version: string;
  parameters: Record<string, unknown> | null;
  holdings_detail: SimulatedHoldingItem[];
  tracking_error: number | null;
  daily_rmse: number | null;
  industry_correlation: number | null;
  top10_recall: number | null;
  stock_weight_pct: number | null;
  bond_weight_pct: number | null;
  cash_weight_pct: number | null;
  confidence: string | null;
  conclusion_status: string;
  is_backtest: boolean;
  backtest_report_date: string | null;
  warnings: string[] | null;
  input_coverage: number | null;
  created_at: string | null;
}

export interface SimulatedHoldingListData {
  fund_code: string;
  results: SimulatedHoldingResult[];
  count: number;
}

export interface TradingAbilityResult {
  fund_code: string;
  calc_date: string | null;
  period_start: string | null;
  period_end: string | null;
  estimated_turnover_rate: number | null;
  estimated_buy_timing_score: number | null;
  estimated_sell_timing_score: number | null;
  estimated_holding_period: number | null;
  estimated_excess_return_from_trading: number | null;
  trading_detail: Array<Record<string, unknown>> | null;
  confidence: string | null;
  conclusion_status: string | null;
  warnings: string[] | null;
}

export interface DynamicAttributionResult {
  id: number;
  fund_code: string;
  calc_date: string | null;
  period_start: string | null;
  period_end: string | null;
  algorithm_name?: string;
  algorithm_version?: string;
  benchmark_symbol?: string | null;
  uses_simulated_holdings?: boolean | null;
  // Fields use estimated_ prefix when uses_simulated_holdings=true, no prefix otherwise.
  // Non-prefixed fields (for computed results from disclosed holdings):
  total_portfolio_return?: number | null;
  total_benchmark_return?: number | null;
  total_allocation_effect?: number | null;
  total_selection_effect?: number | null;
  total_interaction_effect?: number | null;
  // estimated_ prefixed fields (for results using simulated holdings):
  estimated_total_portfolio_return?: number | null;
  estimated_total_benchmark_return?: number | null;
  estimated_total_allocation_effect?: number | null;
  estimated_total_selection_effect?: number | null;
  estimated_total_interaction_effect?: number | null;
  // Residual/IPO/CB/invisible always carry estimated_ prefix:
  estimated_total_residual?: number | null;
  estimated_residual_ratio?: number | null;
  estimated_ipo_return?: number | null;
  estimated_convertible_bond_return?: number | null;
  estimated_invisible_return?: number | null;
  detail?: Record<string, unknown> | null;
  waterfall_data?: Array<Record<string, unknown>> | null;
  confidence: string | null;
  conclusion_status: string | null;
  warnings: string[] | null;
  created_at: string | null;
}

export interface DynamicAttributionListData {
  fund_code: string;
  results: DynamicAttributionResult[];
  count: number;
}

// ---- Quality Dashboard ----

export interface QualitySnapshot {
  source_name: string;
  source_level: string | null;
  entity_type: string;
  fetch_timestamp: string | null;
  record_count: number | null;
  coverage_rate: number | null;
  anomaly_count: number | null;
  is_success: boolean;
  error_message: string | null;
}

export interface QualityTask {
  task_id: string;
  task_type: string | null;
  status: string | null;
  target_entity: string | null;
  started_at: string | null;
  duration_ms: number | null;
  result_summary: string | null;
  error_message: string | null;
}

export interface QualityDashboard {
  table_counts: Record<string, number>;
  freshness: Record<string, string | null>;
  recent_snapshots: QualitySnapshot[];
  recent_tasks: QualityTask[];
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
  health: () =>
    request<{ status: string; database: string; version: string }>("/api/v1/health"),

  getFundProfile: (code: string) =>
    request<FundProfile>(`/api/v1/funds/${code}/profile`),

  getNavMetrics: (code: string, params?: { start?: string; end?: string }) => {
    const search = params
      ? "?" + new URLSearchParams(params as Record<string, string>).toString()
      : "";
    return request<NavMetricsData>(`/api/v1/funds/${code}/nav-metrics${search}`);
  },

  getNavSeries: (code: string, params?: { period?: string; start?: string; end?: string }) => {
    const search = params
      ? "?" + new URLSearchParams(Object.fromEntries(
          Object.entries(params).filter(([, v]) => v !== undefined)
        ) as Record<string, string>).toString()
      : "";
    return request<NavSeriesData>(`/api/v1/funds/${code}/nav-series${search}`);
  },

  getHoldings: (code: string, params?: { report_date?: string }) => {
    const search = params
      ? "?" + new URLSearchParams(params as Record<string, string>).toString()
      : "";
    return request<HoldingsData>(`/api/v1/funds/${code}/holdings${search}`);
  },

  getExposure: (code: string, window = 60) =>
    request<ExposureData>(
      "/api/v1/analysis/exposure",
      { method: "POST", body: JSON.stringify({ fund_code: code, window }) }
    ),

  // R3: 研究包生成/对比已迁移至 v2（含 Phase2 estimated 模块警告 + packet_id 持久化）
  getResearchPacket: (code: string, template = "single_fund_checkup") =>
    request<{ packet_id: string; packet: Record<string, unknown>; markdown: string }>(
      "/api/v2/research/packet",
      { method: "POST", body: JSON.stringify({ fund_code: code, template }) }
    ),

  diffPackets: (body: Record<string, unknown>) =>
    request<DiffData>("/api/v2/research/diff", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // R4: 已保存研究包列表/详情
  listResearchPackets: (params?: { fund_code?: string; limit?: number }) => {
    const sp = new URLSearchParams();
    if (params?.fund_code) sp.set("fund_code", params.fund_code);
    if (params?.limit != null) sp.set("limit", String(params.limit));
    const qs = sp.toString();
    return request<{ packets: ResearchPacketListItem[]; count: number }>(
      `/api/v2/research/packets${qs ? "?" + qs : ""}`,
    );
  },

  getResearchPacketDetail: (packetId: string) =>
    request<ResearchPacketDetail>(
      `/api/v2/research/packets/${encodeURIComponent(packetId)}`,
    ),

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

  searchFunds: (q: string, limit?: number) =>
    request<{ funds: Array<{ fund_code: string; short_name: string; full_name: string; fund_type: string }>; count: number }>(
      `/api/v1/funds/search?q=${encodeURIComponent(q)}&limit=${limit ?? 10}`
    ),

  listExperiments: () =>
    request<ExperimentListData>("/api/v2/experiments"),

  getExperiment: (id: string) =>
    request<ExperimentDetail>(`/api/v2/experiments/${id}`),

  createExperiment: (body: {
    experiment_name: string;
    algorithm_name: string;
    algorithm_version: string;
    parameters: Record<string, unknown>;
    sample_fund_codes: string[];
  }) =>
    request<{ id: string; status: string; experiment_name: string }>(
      "/api/v2/experiments",
      {
        method: "POST",
        body: JSON.stringify(body),
      }
    ),

  runExperiment: (id: string) =>
    request<{
      experiment_id: string;
      status: string;
      fund_count: number;
      success_count: number;
      failure_count: number;
    }>(`/api/v2/experiments/${id}/run`, { method: "POST" }),

  rerunExperiment: (id: string) =>
    request<{ id: string; status: string }>(
      `/api/v2/experiments/${id}/rerun`,
      { method: "POST" }
    ),

  deleteExperiment: (id: string) =>
    request<{ id: string; deleted: boolean }>(
      `/api/v2/experiments/${id}`,
      { method: "DELETE" }
    ),

  getLatestP2BValidationReport: () =>
    request<P2BValidationReport>("/api/v2/validation/p2b/latest"),

  listP2BValidationReports: () =>
    request<P2BValidationReportListData>("/api/v2/validation/p2b/reports"),

  getP2BValidationReport: (reportId: string) =>
    request<P2BValidationReport>(`/api/v2/validation/p2b/reports/${reportId}`),

  compareP2BValidationReports: (baseReportId: string, targetReportId = "latest") => {
    const search = new URLSearchParams({
      base_report_id: baseReportId,
      target_report_id: targetReportId,
    }).toString();
    return request<P2BValidationComparison>(`/api/v2/validation/p2b/compare?${search}`);
  },

  rerunP2BValidationReport: (body?: {
    algorithms?: string[];
    limit?: number;
  }) =>
    request<P2BValidationTask>("/api/v2/validation/p2b/rerun", {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),

  getP2BValidationTask: (taskId: string) =>
    request<P2BValidationTask>(`/api/v2/validation/p2b/tasks/${taskId}`),

  // ---- Scoring ----

  runScoring: (body: {
    fund_codes: string[];
    preset?: string;
    category?: string;
    weights?: Record<string, number>;
  }) =>
    request<ScoringData>("/api/v2/analysis/scoring", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getScoring: (scoreVersion: string) =>
    request<ScoringVersionData>(`/api/v2/analysis/scoring/${scoreVersion}`),

  runScoringBacktest: (body: {
    fund_codes: string[];
    backtest_start: string;
    backtest_end: string;
    preset?: string;
    category?: string;
    weights?: Record<string, number>;
    forward_months?: number;
    min_forward_observations?: number;
  }) =>
    request<ScoringData & {
      ic_mean: number | null;
      ic_ir: number | null;
      monotonicity: boolean | null;
      group_results: Record<string, Record<string, number>> | null;
    }>("/api/v2/analysis/scoring/backtest", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listScoringBacktests: () =>
    request<{ backtests: ScoringBacktestItem[]; total: number }>(
      "/api/v2/analysis/scoring/backtest"
    ),

  getScoringBacktest: (id: number) =>
    request<ScoringBacktestDetail>(`/api/v2/analysis/scoring/backtest/${id}`),

  // ---- Reviewer Annotations ----

  createReviewerAnnotation: (body: {
    fund_code: string;
    annotation_type: AnnotationType;
    target_module?: TargetModule | null;
    detail?: Record<string, unknown>;
    reason: string;
    evidence_ids?: string[];
  }) =>
    request<ReviewerAnnotation>("/api/v2/reviewer-annotations", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listReviewerAnnotations: (params?: {
    fund_code?: string;
    annotation_type?: AnnotationType;
    target_module?: TargetModule;
    limit?: number;
  }) => {
    const search = params
      ? "?" + new URLSearchParams(
          Object.entries(params).filter(([, v]) => v != null) as [string, string][]
        ).toString()
      : "";
    return request<ReviewerAnnotationListData>(
      `/api/v2/reviewer-annotations${search}`
    );
  },

  getReviewerAnnotation: (id: number) =>
    request<ReviewerAnnotation>(`/api/v2/reviewer-annotations/${id}`),

  updateReviewerAnnotation: (
    id: number,
    body: {
      annotation_type?: AnnotationType;
      detail?: Record<string, unknown>;
      reason?: string;
      evidence_ids?: string[];
    }
  ) =>
    request<ReviewerAnnotation>(`/api/v2/reviewer-annotations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  deleteReviewerAnnotation: (id: number) =>
    request<{ deleted: boolean; annotation_id: number }>(
      `/api/v2/reviewer-annotations/${id}`,
      { method: "DELETE" }
    ),

  getFundReviewStatus: (fundCode: string) =>
    request<FundReviewStatus>(
      `/api/v2/reviewer-annotations/funds/${fundCode}/status`
    ),

  // ---- Simulated Holding ----

  listSimulatedHolding: (fundCode: string, limit = 10) =>
    request<SimulatedHoldingListData>(
      `/api/v2/analysis/simulated-holding?fund_code=${fundCode}&limit=${limit}`
    ),

  runSimulatedHolding: (body: {
    fund_code: string;
    start_date?: string | null;
    end_date?: string | null;
    max_positions?: number;
    max_single_weight?: number;
    turnover_penalty?: number;
    industry_penalty?: number;
    window_days?: number;
    rebalance_freq?: "M" | "Q";
  }) =>
    request<{
      experiment_id: string;
      fund_code: string;
      success: boolean;
      result: SimulatedHoldingResult | null;
    }>("/api/v2/analysis/simulated-holding", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ---- Dynamic Attribution ----

  runReturnAttribution: (body: {
    fund_code: string;
    method?: "BHB" | "BF";
    benchmark_symbol?: string | null;
    start_date?: string | null;
    end_date?: string | null;
  }) =>
    request<{
      experiment_id: string;
      fund_code: string;
      success: boolean;
      result: DynamicAttributionResult | null;
    }>("/api/v2/analysis/return-attribution", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listDynamicAttribution: (fundCode: string, limit = 10) =>
    request<DynamicAttributionListData>(
      `/api/v2/analysis/return-attribution?fund_code=${encodeURIComponent(fundCode)}&limit=${limit}`
    ),

  // ---- Dynamic Attribution Readiness ----

  checkDynamicAttributionReadiness: (params?: {
    fund_code?: string[];
    benchmark_symbol?: string;
    min_report_date?: string;
    max_report_date?: string;
    min_return_observations?: number;
    max_snapshot_age_days?: number;
    ready_only?: boolean;
    limit?: number;
  }) => {
    const sp = new URLSearchParams();
    if (params?.fund_code) {
      for (const fc of params.fund_code) sp.append("fund_code", fc);
    }
    if (params?.benchmark_symbol) sp.set("benchmark_symbol", params.benchmark_symbol);
    if (params?.min_report_date) sp.set("min_report_date", params.min_report_date);
    if (params?.max_report_date) sp.set("max_report_date", params.max_report_date);
    if (params?.min_return_observations != null)
      sp.set("min_return_observations", String(params.min_return_observations));
    if (params?.max_snapshot_age_days != null)
      sp.set("max_snapshot_age_days", String(params.max_snapshot_age_days));
    if (params?.ready_only) sp.set("ready_only", "true");
    if (params?.limit != null) sp.set("limit", String(params.limit));
    const qs = sp.toString();
    return request<{
      rows: Array<Record<string, unknown>>;
      total: number;
      ready: number;
    }>(`/api/v2/experiments/dynamic-attribution/readiness${qs ? "?" + qs : ""}`);
  },

  createDynamicAttributionFromReady: (body: {
    experiment_name?: string;
    report_date: string;
    benchmark_symbol?: string | null;
    fund_codes?: string[] | null;
    min_return_observations?: number;
    max_snapshot_age_days?: number;
    limit?: number | null;
  }) =>
    request<{
      experiment_id: string | null;
      sample_fund_codes: string[];
      ready_candidates: number;
      report_date: string;
    }>("/api/v2/experiments/dynamic-attribution/from-ready", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ---- Review Business Endpoints (§5.5.3) ----

  lockSecurities: (body: {
    fund_code: string;
    security_code: string;
    action: "lock" | "exclude";
    target_module?: "simulated_holding" | "scoring" | "dynamic_attribution";
    reason?: string;
    lock_weight?: number | null;
  }) =>
    request<ReviewerAnnotation>("/api/v2/review/lock-securities", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  adjustBenchmark: (body: {
    fund_code: string;
    benchmark_symbol: string;
    custom_weights?: Record<string, number> | null;
    reason?: string;
  }) =>
    request<ReviewerAnnotation>("/api/v2/review/adjust-benchmark", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  annotateConfidence: (body: {
    fund_code: string;
    target_module: "simulated_holding" | "scoring" | "dynamic_attribution";
    adjusted_status: "fact" | "computed" | "estimated" | "observation" | "needs_review";
    original_status?: string | null;
    reason?: string;
  }) =>
    request<ReviewerAnnotation>("/api/v2/review/annotate-confidence", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getReviewHistory: (fundCode: string) =>
    request<ReviewerAnnotationListData>(
      `/api/v2/review/history/${encodeURIComponent(fundCode)}`
    ),

  // ---- Experiment Results (manual record) ----

  recordExperimentResult: (experimentId: string, body: {
    fund_code: string;
    is_success: boolean;
    metrics?: Record<string, unknown> | null;
    error_message?: string | null;
    warnings?: string[] | null;
  }) =>
    request<{ id: number; experiment_id: string }>("/api/v2/experiments/" + experimentId + "/results", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ---- Fund Pool (P2.5-1) ----

  listPools: () =>
    request<{ id: number; name: string; description: string | null; fund_count: number; created_at: string | null; updated_at: string | null }[]>(
      "/api/v2/pools"
    ),

  createPool: (body: { name: string; description?: string }) =>
    request<{ id: number; name: string; description: string | null }>(
      "/api/v2/pools",
      { method: "POST", body: JSON.stringify(body) }
    ),

  getPool: (poolId: number) =>
    request<{ id: number; name: string; description: string | null; created_at: string | null; funds: { fund_code: string; note: string | null; added_at: string | null }[] }>(
      `/api/v2/pools/${poolId}`
    ),

  deletePool: (poolId: number) =>
    request<{ deleted: boolean; pool_id: number }>(
      `/api/v2/pools/${poolId}`,
      { method: "DELETE" }
    ),

  addPoolMember: (poolId: number, body: { fund_code: string; note?: string }) =>
    request<{ id: number; pool_id: number; fund_code: string }>(
      `/api/v2/pools/${poolId}/funds`,
      { method: "POST", body: JSON.stringify(body) }
    ),

  removePoolMember: (poolId: number, fundCode: string) =>
    request<{ removed: boolean; fund_code: string }>(
      `/api/v2/pools/${poolId}/funds/${encodeURIComponent(fundCode)}`,
      { method: "DELETE" }
    ),

  // ---- Saved Screens (P2.5-1) ----

  listScreens: () =>
    request<{ id: number; name: string; filters: Record<string, unknown>; sort_by: string | null; sort_order: string | null; created_at: string | null }[]>(
      "/api/v2/screens"
    ),

  saveScreen: (body: { name: string; filters: Record<string, unknown>; sort_by?: string; sort_order?: string }) =>
    request<{ id: number; name: string }>(
      "/api/v2/screens",
      { method: "POST", body: JSON.stringify(body) }
    ),

  deleteScreen: (screenId: number) =>
    request<{ deleted: boolean; screen_id: number }>(
      `/api/v2/screens/${screenId}`,
      { method: "DELETE" }
    ),

  // ---- Trading Ability (P2.6-1) ----

  runTradingAbility: (body: {
    fund_code: string;
    start_date?: string | null;
    end_date?: string | null;
    evaluation_window_days?: number;
  }) =>
    request<TradingAbilityResult & { id: number }>(
      "/api/v2/analysis/trading-ability",
      { method: "POST", body: JSON.stringify(body) }
    ),

  listTradingAbility: (fundCode: string, limit = 10) =>
    request<{ results: TradingAbilityResult[]; count: number }>(
      `/api/v2/analysis/trading-ability/${encodeURIComponent(fundCode)}?limit=${limit}`
    ),

  // ---- Export (P2.5-2) ----

  exportResearchPacket: (fundCode: string, format: "markdown" | "json" | "csv" = "markdown") =>
    request<{ filename: string; format: string; media_type: string; content_base64: string; size_bytes: number }>(
      `/api/v2/research/packet/${encodeURIComponent(fundCode)}/export?format=${format}`
    ),

  exportScreenResults: (body: {
    filters: Record<string, unknown>;
    sort_by?: string;
    sort_order?: string;
    limit?: number;
    format?: "csv" | "json";
  }) =>
    request<{ filename: string; format: string; media_type: string; content_base64: string; row_count: number }>(
      "/api/v2/funds/screen/export",
      { method: "POST", body: JSON.stringify(body) }
    ),

  // ---- Evidence (P2.5-4) ----
  listEvidence: (params?: {
    fund_code?: string;
    source_level?: string;
    evidence_type?: string;
    limit?: number;
    offset?: number;
  }) => {
    const sp = new URLSearchParams();
    if (params?.fund_code) sp.set("fund_code", params.fund_code);
    if (params?.source_level) sp.set("source_level", params.source_level);
    if (params?.evidence_type) sp.set("evidence_type", params.evidence_type);
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.offset != null) sp.set("offset", String(params.offset));
    const qs = sp.toString();
    return request<{
      items: EvidenceRecord[];
      total: number;
      limit: number;
      offset: number;
    }>(`/api/v2/evidence${qs ? "?" + qs : ""}`);
  },

  getEvidence: (evidenceId: string) =>
    request<EvidenceRecord>(`/api/v2/evidence/${encodeURIComponent(evidenceId)}`),

  getQualityDashboard: () =>
    request<QualityDashboard>("/api/v2/quality/dashboard"),

  // ---- Phase 3: Fingerprint & Similarity ----

  generateFingerprint: (fundCode: string) =>
    request<Record<string, unknown>>(`/api/v2/fingerprint/${encodeURIComponent(fundCode)}`, {
      method: "POST",
    }),

  getFingerprint: (fundCode: string) =>
    request<Record<string, unknown>>(`/api/v2/fingerprint/${encodeURIComponent(fundCode)}`),

  batchFingerprint: (body: { fund_codes: string[]; calc_date?: string | null }) =>
    request<{
      total: number;
      success_count: number;
      failure_count: number;
      errors: Array<{ fund_code: string; error: string }>;
      calc_date: string | null;
    }>("/api/v2/fingerprint/batch", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  compareFingerprints: (fundCodes: string[]) =>
    request<{
      fund_codes: string[];
      comparison_data: Record<string, unknown>;
      similarity_matrix: Record<string, unknown>;
      overlap_analysis: Record<string, unknown>;
      missing_codes: string[];
    }>("/api/v2/fingerprint/compare", {
      method: "POST",
      body: JSON.stringify({ fund_codes: fundCodes }),
    }),

  findSimilarFunds: (fundCode: string, params?: { metric_space?: string; top_n?: number; same_type_only?: boolean }) =>
    request<{ similar_funds: Array<Record<string, unknown>>; fund_code: string; metric_space: string; count: number }>(
      `/api/v2/fingerprint/${encodeURIComponent(fundCode)}/similar`,
      { method: "POST", body: JSON.stringify(params ?? {}) }
    ),

  compareFunds: (fundCodes: string[], dimensions?: string[]) =>
    request<{
      basic_info: Record<string, Record<string, unknown>>;
      comparison_data: Record<string, Record<string, unknown>>;
      similarity_matrix: Record<string, unknown> | null;
      dimensions: string[];
    }>(
      "/api/v2/funds/compare",
      { method: "POST", body: JSON.stringify({ fund_codes: fundCodes, dimensions }) }
    ),

  // ---- Phase 3: Anomaly Detection ----

  scanAnomalies: (body: { scope: string; scope_id?: string | null; rules?: string[] | null; params?: Record<string, unknown> | null }) =>
    request<{ anomalies: Array<Record<string, unknown>>; total: number; rules_run: string[] }>(
      "/api/v2/anomalies/scan",
      { method: "POST", body: JSON.stringify(body) }
    ),

  listAnomalies: (params?: { fund_code?: string; rule_name?: string; severity?: string; limit?: number }) => {
    const sp = new URLSearchParams();
    if (params?.fund_code) sp.set("fund_code", params.fund_code);
    if (params?.rule_name) sp.set("rule_name", params.rule_name);
    if (params?.severity) sp.set("severity", params.severity);
    if (params?.limit != null) sp.set("limit", String(params.limit));
    const qs = sp.toString();
    return request<{ anomalies: Array<Record<string, unknown>>; total: number }>(
      `/api/v2/anomalies${qs ? "?" + qs : ""}`
    );
  },

  getAnomaly: (id: number) =>
    request<Record<string, unknown>>(`/api/v2/anomalies/${id}`),

  // ---- Phase 3: Pool Alerts ----

  scanPoolAlerts: (poolId: number, alertTypes?: string[]) =>
    request<{ results: Array<Record<string, unknown>>; total: number }>(
      `/api/v2/pools/${poolId}/alerts/scan`,
      { method: "POST", body: JSON.stringify({ alert_types: alertTypes }) }
    ),

  getPoolAlerts: (poolId?: number, isRead?: boolean, limit = 50) => {
    const sp = new URLSearchParams();
    if (poolId != null) sp.set("pool_id", String(poolId));
    if (isRead != null) sp.set("is_read", String(isRead));
    sp.set("limit", String(limit));
    return request<{ items: Array<Record<string, unknown>>; total: number }>(
      `/api/v2/alerts?${sp.toString()}`
    );
  },

  markAlertRead: (alertId: number) =>
    request<Record<string, unknown>>(`/api/v2/alerts/${alertId}/read`, { method: "POST" }),

  createAlertRule: (poolId: number, body: { fund_code: string; alert_type: string; params?: Record<string, unknown> }) =>
    request<{ id: number; pool_id: number; fund_code: string; alert_type: string; params: Record<string, unknown>; is_active: boolean }>(
      `/api/v2/pools/${poolId}/alert-rules`,
      { method: "POST", body: JSON.stringify(body) }
    ),

  listAlertRules: (poolId: number, fundCode?: string) => {
    const sp = new URLSearchParams();
    if (fundCode) sp.set("fund_code", fundCode);
    const qs = sp.toString();
    return request<{ rules: Array<{ id: number; pool_id: number; fund_code: string; alert_type: string; params: Record<string, unknown>; is_active: boolean; created_at: string | null }>; total: number }>(
      qs ? `/api/v2/pools/${poolId}/alert-rules?${qs}` : `/api/v2/pools/${poolId}/alert-rules`
    );
  },

  deleteAlertRule: (poolId: number, ruleId: number) =>
    request<Record<string, unknown>>(`/api/v2/pools/${poolId}/alert-rules/${ruleId}`, { method: "DELETE" }),

  // ---- Phase 3: Reverse Lookup ----

  reverseLookup: (body: { stock_codes: string[]; fund_scope?: string; scope_id?: string; method?: string; top_n?: number }) =>
    request<{ results: Array<Record<string, unknown>>; stock_coverage: Record<string, number>; method: string; fund_count: number }>(
      "/api/v2/analysis/reverse-lookup",
      { method: "POST", body: JSON.stringify(body) }
    ),

  // ---- Phase 3: Research Templates ----

  seedTemplates: () =>
    request<{ inserted: number }>("/api/v2/templates/seed", { method: "POST" }),

  listTemplates: (builtinOnly = false) =>
    request<{ templates: Array<Record<string, unknown>>; total: number }>(
      `/api/v2/templates?builtin_only=${builtinOnly}`
    ),

  getTemplate: (templateId: string) =>
    request<Record<string, unknown>>(`/api/v2/templates/${encodeURIComponent(templateId)}`),

  runTemplate: (templateId: string, inputs: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/v2/templates/${encodeURIComponent(templateId)}/run`, {
      method: "POST",
      body: JSON.stringify({ inputs }),
    }),

  listTemplateRuns: (templateId?: string, limit = 20) => {
    const sp = new URLSearchParams();
    if (templateId) sp.set("template_id", templateId);
    sp.set("limit", String(limit));
    return request<{ runs: Array<Record<string, unknown>>; total: number }>(
      `/api/v2/templates/runs?${sp.toString()}`
    );
  },

  // ---- Phase 3: Dashboard ----

  getDashboard: (fundCodes?: string[]) => {
    const sp = new URLSearchParams();
    if (fundCodes && fundCodes.length > 0) {
      fundCodes.forEach((c) => sp.append("fund_codes", c));
    }
    const qs = sp.toString();
    return request<{
      today_changes: Record<string, unknown>;
      pool_monitoring: Record<string, unknown>;
      algorithm_alerts: Record<string, unknown>;
      ai_alerts: Record<string, unknown>;
      market_overview: Record<string, unknown>;
      generated_at: string;
      warnings: string[];
    }>(`/api/v2/dashboard${qs ? "?" + qs : ""}`);
  },
};
