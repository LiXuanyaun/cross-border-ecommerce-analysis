import type { components } from "./generated/api";

export type ApiStatus = "SUCCESS" | "PARTIAL" | "SKIPPED" | "FAILED" | "FATAL";
export type AgentSessionRequest = components["schemas"]["AgentSessionRequest"];
export type AgentRunRequest = components["schemas"]["AgentRunRequest"];
export type WorkItemPatch = components["schemas"]["WorkItemPatch"];

export interface ApiEnvelope<T> {
  status: ApiStatus;
  data: T;
  meta: Record<string, unknown>;
  limitations: string[];
}

export interface Kpi {
  id?: string;
  label: string;
  value: number | null;
  format: "currency" | "percent" | "integer";
  change?: number | null;
  tone?: "blue" | "violet" | "green" | "orange";
  previous_value?: number | null;
  sparkline?: Array<{ label: string; value: number | null }>;
  basis?: string;
  threshold?: string;
}

export interface OverviewPeriod {
  start: string;
  end: string;
  type?: string;
}

export interface OverviewTrend {
  grain: "day" | "week";
  current_period: OverviewPeriod;
  comparison_period: OverviewPeriod;
  rows: Array<{
    label: string;
    current_date: string;
    comparison_date: string;
    current: number | null;
    comparison: number | null;
  }>;
}

export interface OverviewTask {
  id: string;
  insight_id: string;
  object: string;
  object_type: string;
  metric_id: string;
  metric_label: string;
  anomaly: string;
  finding: string;
  impact_amount: number | null;
  impact_type: string;
  target_threshold: string;
  priority: string;
  analysis_status: string;
  status: string;
  owner: string;
  deadline: string | null;
  result_note: string;
  review_result: string;
  close_reason: string;
  closed_by: string;
  closed_at: string | null;
  current_value: number | null;
  comparison_value: number | null;
  change_rate: number | null;
  current_period: OverviewPeriod | null;
  comparison_period: OverviewPeriod | null;
  diagnosis: {
    status: string;
    summary: string;
    confidence_score: number;
    drivers: Array<Record<string, unknown>>;
  };
  recommendation: {
    action: string;
    rationale: string;
    expected_metric: string | null;
    validation_period: string | null;
    stop_condition: string | null;
  };
  evidence: {
    ids: string[];
    source_fields: string[];
    formula: string | null;
    row_count: number | null;
    quality_level: string;
  };
  created_at: string;
}

export interface OverviewMarket {
  rank: number;
  market: string;
  name: string;
  gmv: number;
  share: number | null;
  yoy: number | null;
  previous_gmv: number;
}

export interface OverviewCategory {
  category: string;
  name: string;
  gmv: number;
  previous: number | null;
  change: number | null;
  change_rate: number | null;
  share: number | null;
}

export interface OverviewOpportunity {
  id: string;
  object: string;
  object_type: string;
  status: string;
  estimated_growth: number;
  growth_rate: number | null;
  basis: string;
  current_period: string;
  comparison_period: string;
  current_gmv: number;
  previous_gmv: number | null;
  recommended_action: string;
  guardrail_metrics: string[];
  validation_period: string;
  stop_condition: string;
  evidence_ids: string[];
}

export interface OverviewInsight {
  id: string;
  created_at: string;
  period: string;
  priority: string;
  object: string;
  metric_label: string;
  finding: string;
  analysis_status: string;
  change_rate: number | null;
  impact_amount: number | null;
  sustainability: {
    level: string;
    reason: string;
    same_direction_periods: number;
    profit_margin_guardrail: boolean;
    return_rate_guardrail: boolean;
  };
  history: {
    lookback_months: number;
    similar_occurrences: number;
    similar_periods: Array<{ period: string; change_rate: number | null; impact_amount: number | null }>;
    recent_changes: Array<{ period: string; change_rate: number | null }>;
  };
  evidence: OverviewTask["evidence"];
  recommendation: OverviewTask["recommendation"];
}

export interface OverviewMethodologyItem {
  basis: string;
  comparison: string;
  threshold: string;
}

export interface OverviewData {
  period: OverviewPeriod;
  current_period: OverviewPeriod;
  comparison_period: OverviewPeriod;
  selection_period: OverviewPeriod;
  kpis: Kpi[];
  trends: { day: OverviewTrend; week: OverviewTrend };
  trend: Array<Record<string, number | string | null>>;
  markets: OverviewMarket[];
  market_comparison_period: OverviewPeriod;
  categories: OverviewCategory[];
  tasks: OverviewTask[];
  opportunities: OverviewOpportunity[];
  insights: OverviewInsight[];
  methodology: {
    kpis: OverviewMethodologyItem;
    trend: OverviewMethodologyItem;
    tasks: OverviewMethodologyItem;
    markets: OverviewMethodologyItem;
    products: OverviewMethodologyItem;
    opportunities: OverviewMethodologyItem;
    insights: OverviewMethodologyItem;
  };
  currency: string;
}

export type TopicValueFormat = "currency" | "percent" | "integer" | "decimal" | "days" | "text" | "category";

export interface TopicMetric {
  id: string;
  label: string;
  value: number | null;
  format: TopicValueFormat;
  change: number | null;
  sparkline: Array<{ label: string; value: number | null }>;
}

export interface TopicTrend {
  title: string;
  format: TopicValueFormat;
  secondary_label: string | null;
  secondary_format: TopicValueFormat | null;
  rows: Array<{ period: string; value: number | null; secondary: number | null }>;
}

export interface TopicComposition {
  title: string;
  format: TopicValueFormat;
  rows: Array<{ name: string; value: number; chart_value: number; share: number | null }>;
}

export interface TopicRanking {
  title: string;
  format: TopicValueFormat;
  secondary_format: TopicValueFormat | null;
  rows: Array<{ rank: number; name: string; value: number; secondary: number | string | null }>;
}

export interface TopicColumn {
  key: string;
  label: string;
  format: TopicValueFormat;
}

export interface TopicFinding {
  id: string;
  priority: string;
  title: string;
  finding: string;
}

export interface TopicEvidence {
  id: string;
  metric: string;
  value: number | null;
  unit: string;
  claim: string;
  formula: string;
  sample_size: number;
  confidence: string;
  source_fields: string;
}

export interface TopicAction {
  id: string;
  title: string;
  action: string;
  owner: string;
  validation_period: string;
}

export interface TopicDecisionTrend {
  title: string;
  format: TopicValueFormat;
  current_period: OverviewPeriod;
  comparison_period: OverviewPeriod;
  rows: Array<{
    label: string;
    current_period: string;
    comparison_period: string | null;
    current: number | null;
    comparison: number | null;
  }>;
}

export interface TopicDecisionItem {
  id: string;
  rank: number;
  object: string;
  current_value: number | null;
  comparison_value: number | null;
  change_rate: number | null;
  impact_amount: number;
  impact_share: number | null;
  status: string;
  orders: number;
}

export interface TopicDecisionBoard {
  basis: string;
  trend: TopicDecisionTrend;
  anomalies: TopicDecisionItem[];
  drivers: TopicDecisionItem[];
}

export interface TopicReport {
  title: string;
  generated_at: string;
  period: OverviewPeriod;
  filters: { market: string; category: string };
  summary: string;
  findings: TopicFinding[];
  evidence: TopicEvidence[];
  actions: TopicAction[];
}

export interface TopicData {
  topic: string;
  summary: string;
  metrics: TopicMetric[];
  trend: TopicTrend;
  composition: TopicComposition;
  ranking: TopicRanking;
  columns: TopicColumn[];
  details: Array<Record<string, unknown>>;
  pagination: { page: number; page_size: number; total: number; pages: number };
  filters: {
    start: string;
    end: string;
    markets: Array<{ value: string; label: string }>;
    categories: Array<{ value: string; label: string }>;
  };
  decision_board: TopicDecisionBoard;
  ai: { findings: TopicFinding[]; evidence: TopicEvidence[]; actions: TopicAction[] };
  report: TopicReport;
}

export interface DatasetSummary {
  dataset_id: string;
  name: string;
  description: string;
  source_type: string;
  row_count: number;
  status: string;
  quality_score: number;
  period_start: string;
  period_end: string;
  updated_at: string;
  is_demo: boolean;
}

export interface DecisionDriver {
  rank: number;
  name: string;
  driver_code: string;
  impact_amount: number;
  contribution_share: number | null;
  unit: string;
}

export interface DecisionEvidence {
  metric: string;
  metric_id: string;
  current_value: number | null;
  comparison_value: number | null;
  absolute_change: number | null;
  change_rate: number | null;
  unit: string;
  source: string;
  formula: string;
  period_start: string;
  period_end: string;
  comparison_start: string | null;
  comparison_end: string | null;
  status: ApiStatus;
  source_fields?: string[];
  row_count?: number;
  limitations?: string[];
}

export interface DecisionAction {
  priority: string;
  action_type: string;
  title: string;
  action: string;
  steps: string[];
  reason: string;
  affected_object: string;
  owner_role: string;
  expected_metric: string;
  expected_benefit: {
    status: ApiStatus;
    value: number | null;
    message: string;
  };
  validation_target: {
    metric: string;
    target_value: number | null;
    message: string;
  };
  guardrail_metrics: string[];
  validation_period: string;
  stop_condition: string;
  limitations: string[];
}

export interface DecisionCase {
  rank: number;
  case_id: string;
  period_start: string;
  period_end: string;
  comparison_start: string | null;
  comparison_end: string | null;
  anomaly: {
    object_name: string;
    object_type: string;
    metric: string;
    metric_id: string;
    current_value: number | null;
    comparison_value: number | null;
    absolute_change: number | null;
    change_rate: number | null;
    impact_amount: number | null;
    impact_ratio: number | null;
    unit: string;
    priority: string;
    severity: string;
  };
  finding: {
    what_happened: string;
    impact_level: string;
    main_object: string;
    summary: string;
    confidence_score: number;
  };
  drivers: DecisionDriver[];
  evidence: DecisionEvidence[];
  actions: DecisionAction[];
  limitations: string[];
  chain: {
    anomaly: string;
    drivers: string[];
    object: string;
    evidence: string[];
    actions: string[];
  };
}

export interface DecisionBrief {
  status: ApiStatus;
  message: string;
  period_start?: string;
  cases: DecisionCase[];
  key_findings: DecisionCase["finding"][];
  top_impact: Array<
    DecisionCase["anomaly"] & { rank: number; case_id: string }
  >;
  unavailable_metrics: Array<{
    metric_id: string;
    metric: string;
    status: ApiStatus;
    reason: string;
  }>;
}
