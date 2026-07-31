import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { AnalyticsPage } from "../features/analytics/AnalyticsPage";
import { AppStateProvider } from "../state/app";

vi.mock("../components/EChart", () => ({
  EChart: () => <div data-testid="topic-chart">chart</div>,
}));

const finding = {
  id: "customer-healthy-scale",
  priority: "P3",
  title: "客户规模与价值",
  finding: "当前覆盖 100 名客户，人均贡献 ¥500。",
};
const evidence = {
  contract_version: "topic-evidence.v1",
  id: "customer-count",
  metric: "客户数",
  value: 100,
  unit: "",
  claim: "当前分析范围覆盖100名去重客户。",
  formula: "count(distinct customer_id)",
  sample_size: 300,
  confidence: "可复算",
  source_fields: ["customer_id"],
  period: { start: "2025-01-01", end: "2025-06-30" },
  filters: {},
  quality_state: "PASS",
  limitations: [],
};
const driver = {
  id: "customer-segment-1",
  rank: 1,
  object: "VIP客户",
  current_value: 20,
  comparison_value: null,
  change_rate: null,
  impact_amount: 25000,
  impact_share: 0.5,
  status: "贡献结构",
  orders: 20,
};
const action = {
  id: "customer-monitor-value",
  title: "维持分群运营并按月复核客户价值",
  action: "每月复核",
  owner: "客户运营",
  validation_period: "下一个完整月",
  trigger_condition: "人均贡献环比下降 10% 时复查",
};
const topicPayload = {
  topic: "customer",
  summary: "当前范围未发现符合规则的客户异常。",
  metrics: [{ id: "customers", label: "客户数", value: 100, format: "integer", change: 0.05, sparkline: [] }],
  trend: { title: "月度活跃客户趋势", format: "integer", secondary_label: null, secondary_format: null, rows: [] },
  composition: { title: "RFM 客户构成", format: "integer", rows: [{ name: "VIP客户", value: 20, chart_value: 20, share: 0.2 }] },
  ranking: { title: "客户分群价值排名", format: "currency", secondary_format: "integer", rows: [] },
  columns: [],
  details: [],
  pagination: { page: 1, page_size: 20, total: 100, pages: 5 },
  filters: { start: "2025-01-01", end: "2025-06-30", markets: [], categories: [] },
  decision_board: {
    basis: "当前完整周期",
    state: { status: "HEALTHY", title: "当前范围未发现符合规则的客户异常", description: "继续查看客户规模、分群贡献和监测条件。", missing_fields: [] },
    trend: { title: "活跃客户趋势对比", format: "integer", current_period: { start: "2025-04-01", end: "2025-06-30" }, comparison_period: { start: "2025-01-01", end: "2025-03-31" }, rows: [] },
    anomalies: [],
    drivers: [driver],
  },
  ai: { findings: [finding], evidence: [evidence], actions: [action] },
  report: { title: "客户专题分析报告", generated_at: "2026-07-31", period: { start: "2025-01-01", end: "2025-06-30" }, filters: { market: "全部市场", category: "全部品类" }, summary: "正常", findings: [finding], evidence: [evidence], actions: [action] },
};

afterEach(() => vi.restoreAllMocks());

it("renders customer healthy state with structure, evidence and monitoring actions", async () => {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: { getItem: () => "demo-all", setItem: vi.fn(), removeItem: vi.fn() },
  });
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: true,
    json: async () => ({ status: "SUCCESS", data: topicPayload, meta: { dataset_id: "demo-all", scope_id: "scope-test" }, limitations: [] }),
  })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={client}>
      <AppStateProvider>
        <MemoryRouter initialEntries={["/analytics?topic=customer&start=2025-01-01&end=2025-06-30"]}>
          <Routes><Route path="/analytics" element={<AnalyticsPage />} /></Routes>
        </MemoryRouter>
      </AppStateProvider>
    </QueryClientProvider>,
  );

  expect(await screen.findByText("当前范围未发现符合规则的客户异常")).toBeInTheDocument();
  expect(screen.getByText("当前覆盖 100 名客户，人均贡献 ¥500。")).toBeInTheDocument();
  expect(screen.getAllByText("VIP客户")).not.toHaveLength(0);
  expect(screen.getByText("分群贡献结构")).toBeInTheDocument();
  expect(screen.getByText("当前分析范围覆盖100名去重客户。")).toBeInTheDocument();
  expect(screen.getByText("维持分群运营并按月复核客户价值")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /维持分群运营并按月复核客户价值/ }));
  expect(screen.getByText("何时触发复查")).toBeInTheDocument();
  expect(screen.getByText("人均贡献环比下降 10% 时复查")).toBeInTheDocument();
});
