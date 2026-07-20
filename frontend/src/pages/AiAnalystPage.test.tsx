import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DecisionBrief, DecisionCase } from "../types";
import {
  ActionsCard,
  DriversCard,
  EvidenceSummaryCard,
  KeyFindingsCard,
  TopImpactPanel,
} from "./AiAnalystPage";

const decisionCase: DecisionCase = {
  rank: 1,
  case_id: "internal-case-reference",
  period_start: "2025-08-01",
  period_end: "2025-08-31",
  comparison_start: "2025-07-01",
  comparison_end: "2025-07-31",
  anomaly: {
    object_name: "Electronics",
    object_type: "类目",
    metric: "GMV（成交总额）",
    metric_id: "gmv",
    current_value: 129196.57,
    comparison_value: 179237.53,
    absolute_change: -50040.96,
    change_rate: -0.279,
    impact_amount: -50040.96,
    impact_ratio: -0.187,
    unit: "CNY",
    priority: "P0",
    severity: "HIGH",
  },
  finding: {
    what_happened: "Electronics GMV（成交总额）下降",
    impact_level: "P0",
    main_object: "Electronics",
    summary: "Electronics GMV 较对比周期下降 27.9%，主要由客单价贡献。",
    confidence_score: 96,
  },
  drivers: [
    {
      rank: 1,
      name: "客单价",
      driver_code: "aov",
      impact_amount: -42000,
      contribution_share: 0.839,
      unit: "CNY",
    },
    {
      rank: 2,
      name: "订单成交金额",
      driver_code: "amount",
      impact_amount: -0.24,
      contribution_share: 0.001,
      unit: "CNY",
    },
  ],
  evidence: [
    {
      metric: "GMV（成交总额）",
      metric_id: "gmv",
      current_value: 129196.57,
      comparison_value: 179237.53,
      absolute_change: -50040.96,
      change_rate: -0.279,
      unit: "CNY",
      source: "SQL 注册指标聚合",
      formula: "所选范围内的订单成交金额",
      period_start: "2025-08-01",
      period_end: "2025-08-31",
      comparison_start: "2025-07-01",
      comparison_end: "2025-07-31",
      status: "SUCCESS",
    },
  ],
  actions: [
    {
      priority: "P0",
      action_type: "OPTIMIZE",
      title: "对 Electronics 高影响 SKU 开展价格带验证",
      action: "选取 Top 10 SKU 建立价格带与折扣对照组。",
      steps: ["生成影响清单", "建立对照组"],
      reason: "GMV 下降且客单价贡献最大。",
      affected_object: "Electronics",
      owner_role: "商品运营负责人",
      expected_metric: "GMV（成交总额）",
      expected_benefit: {
        status: "SKIPPED",
        value: null,
        message: "当前数据不足，无法可靠估算预期收益；需要通过受控实验验证。",
      },
      validation_target: {
        metric: "GMV（成交总额）",
        target_value: 179237.53,
        message: "以恢复至对比周期水平作为验证目标。",
      },
      guardrail_metrics: ["利润率", "退货率"],
      validation_period: "下一个完整可比较周期",
      stop_condition: "利润率下降时停止",
      limitations: ["缺少广告流量"],
    },
  ],
  limitations: ["缺少广告流量"],
  chain: {
    anomaly: "Electronics · GMV",
    drivers: ["客单价"],
    object: "Electronics",
    evidence: ["GMV（成交总额）"],
    actions: ["对 Electronics 高影响 SKU 开展价格带验证"],
  },
};

const brief: DecisionBrief = {
  status: "SUCCESS",
  message: "",
  period_start: "2025-08-01",
  cases: [decisionCase],
  key_findings: [decisionCase.finding],
  top_impact: [
    { ...decisionCase.anomaly, rank: 1, case_id: decisionCase.case_id },
  ],
  unavailable_metrics: [],
};

describe("AI BI result modules", () => {
  it("links the selected impact object to the decision case", () => {
    const onSelect = vi.fn();
    render(
      <TopImpactPanel
        brief={brief}
        selectedCaseId=""
        onSelectCase={onSelect}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Electronics/ }));
    expect(onSelect).toHaveBeenCalledWith(decisionCase.case_id);
    expect(screen.getByText("-18.7%")).toBeInTheDocument();
  });

  it("renders findings, drivers, business evidence and executable action without internal ids", () => {
    const { container } = render(
      <>
        <KeyFindingsCard
          brief={brief}
          selectedCaseId={decisionCase.case_id}
          onSelectCase={() => undefined}
        />
        <DriversCard item={decisionCase} />
        <EvidenceSummaryCard item={decisionCase} />
        <ActionsCard item={decisionCase} />
      </>,
    );

    expect(screen.getByText(/主要对象 Electronics/)).toBeInTheDocument();
    expect(screen.getByText(/贡献 83.9%/)).toBeInTheDocument();
    expect(screen.getByText(/-¥0.24/)).toBeInTheDocument();
    expect(screen.getByText("来源：SQL 注册指标聚合")).toBeInTheDocument();
    expect(
      screen.getByText("对 Electronics 高影响 SKU 开展价格带验证"),
    ).toBeInTheDocument();
    expect(screen.getByText(/无法可靠估算预期收益/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/metric_facts|ev_|scope_/);
  });
});
