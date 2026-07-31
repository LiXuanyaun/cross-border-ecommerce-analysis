import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BusinessAnalysisPage } from "./BusinessAnalysisPage";
import { AppStateProvider } from "../state/app";

vi.mock("../components/EChart", () => ({
  EChart: () => <div data-testid="business-chart">chart</div>,
}));

const payload = {
  topic: "advertising",
  dataset_id: "adventureworks-test",
  scope_id: "scope_test",
  period: { start: "2013-05-01", end: "2013-10-01" },
  filters: {},
  filter_options: { country: ["DE"], channel: ["Search"], platform: ["Google Ads"], campaign_id: ["CMP-DE-SEARCH-GENERIC"] },
  data_source: { is_simulated: true, label: "模拟数据", description: "AdventureWorks + synthetic_extension", data_origin: "synthetic_extension" },
  quality: { status: "WARNING", association_status: "VALIDATED", limitations: ["模拟数据"] },
  metrics: [{ id: "ad.spend_usd", label: "广告花费", value: 150, format: "currency", formula: "sum(spend_usd)", currency: "USD", evidence_id: "ev_1" }],
  trend: { title: "广告花费与转化效率趋势", grain: "month", rows: [{ period: "2013-05", spend_usd: 50, conversions: 5 }, { period: "2013-10", spend_usd: 100, conversions: 1 }], series: ["spend_usd", "conversions"] },
  ranking: { title: "活动投入与效率排名", dimension: "campaign_id", rows: [{ campaign_id: "CMP-DE-SEARCH-GENERIC", spend_usd: 150 }] },
  anomalies: [{ id: "an_1", rule_id: "AD_SPEND_UP_CVR_DOWN", rule_version: "1.0.0", title: "花费上升但转化效率下降", entity: "CMP-DE-SEARCH-GENERIC", status: "需关注", current_value: 0.01, comparison_value: 0.05, change_rate: -0.8, threshold: "spend_change >= 50% AND cvr_change <= -20%", reason: "达到规则阈值", recommendation: "暂停低效投放", evidence_ids: ["ev_1"], limitations: ["模拟数据"] }],
  causes: [{ anomaly_id: "an_1", entity: "CMP-DE-SEARCH-GENERIC", explanation: "达到规则阈值，但不证明因果。", evidence_ids: ["ev_1"] }],
  actions: [{ anomaly_id: "an_1", priority: "P1", title: "暂停低效投放", threshold: "CVR 恢复", evidence_ids: ["ev_1"] }],
  evidence: [{ evidence_id: "ev_1", metric_id: "ad.spend_usd", metric: "广告花费", value: 150, formula: "sum(spend_usd)", source_table: "fact_ad_performance_daily", period: { start: "2013-05-01", end: "2013-10-01" }, comparison_period: null, threshold: null, sample_size: 2, record_keys: ["CMP-DE-SEARCH-GENERIC"], limitations: ["模拟数据"] }],
  details: [],
};

afterEach(() => vi.restoreAllMocks());

describe("BusinessAnalysisPage", () => {
  it("keeps simulation provenance visible and renders metrics, anomalies, causes and actions", async () => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: { getItem: () => "adventureworks-test", setItem: vi.fn(), removeItem: vi.fn() },
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const data = url.includes("/business/datasets")
        ? [{ dataset_id: "adventureworks-test", name: "AdventureWorks 多业务分析", imported_at: "2026-07-28", is_simulated: true, source_label: "模拟数据" }]
        : payload;
      return { ok: true, json: async () => ({ status: "SUCCESS", data, meta: {}, limitations: [] }) } as Response;
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><AppStateProvider><MemoryRouter initialEntries={["/business/advertising"]}><Routes><Route path="/business/:topic" element={<BusinessAnalysisPage />} /></Routes></MemoryRouter></AppStateProvider></QueryClientProvider>);

    expect(await screen.findAllByText("演示推算数据")).not.toHaveLength(0);
    expect(await screen.findAllByText("广告花费")).not.toHaveLength(0);
    expect(screen.getByText("花费上升但转化效率下降")).toBeInTheDocument();
    expect(screen.getByText("原因说明")).toBeInTheDocument();
    expect(screen.getByText("行动建议")).toBeInTheDocument();
    expect(screen.getByTestId("business-chart")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("synthetic_extension");
    expect(document.body).not.toHaveTextContent("scope_test");
    expect(document.body).not.toHaveTextContent("AD_SPEND_UP_CVR_DOWN");
    expect(document.body).not.toHaveTextContent("spend_change >= 50%");
    expect(document.body).not.toHaveTextContent("sum(spend_usd)");
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });

  it("shows the available period and does not mount a chart when the selected range is out of range", async () => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: { getItem: () => "adventureworks-test", setItem: vi.fn(), removeItem: vi.fn() },
    });
    const outOfRange = {
      ...payload,
      data_state: "OUT_OF_RANGE",
      period: { start: "2030-01-01", end: "2030-12-31" },
      available_periods: [{ start: "2013-01-01", end: "2014-01-28" }],
      recommended_period: { start: "2013-02-01", end: "2014-01-28" },
      metrics: payload.metrics.map(item => ({ ...item, value: null })),
      trend: { ...payload.trend, rows: [] },
      ranking: { ...payload.ranking, rows: [] },
      anomalies: [], causes: [], actions: [], evidence: [], details: [],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const data = String(input).includes("/business/datasets")
        ? [{ dataset_id: "adventureworks-test", name: "AdventureWorks 多业务分析", imported_at: "2026-07-28", is_simulated: true, source_label: "模拟数据" }]
        : outOfRange;
      return { ok: true, json: async () => ({ status: "SUCCESS", data, meta: {}, limitations: [] }) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><AppStateProvider><MemoryRouter initialEntries={["/business/advertising?start=2030-01-01&end=2030-12-31"]}><Routes><Route path="/business/:topic" element={<BusinessAnalysisPage />} /></Routes></MemoryRouter></AppStateProvider></QueryClientProvider>);

    expect(await screen.findByText("当前选择时期没有该专题事实")).toBeInTheDocument();
    expect(screen.getByText(/2013-01-01 至 2014-01-28/)).toBeInTheDocument();
    expect(screen.queryByTestId("business-chart")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "使用可用时期" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("start=2013-02-01") && String(input).includes("end=2014-01-28"))).toBe(true));
  });
});
