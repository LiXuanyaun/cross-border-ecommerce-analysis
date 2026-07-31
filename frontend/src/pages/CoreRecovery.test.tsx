import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ChatMessage } from "../features/ai-analyst/AiAnalystPage";
import { EvidenceDetail } from "../features/analytics/AnalyticsPage";
import { AppStateProvider, useAppState } from "../state/app";

function DatasetProbe() {
  const { datasetId, setDatasetId } = useAppState();
  return <button onClick={() => setDatasetId("demo-all")}>{datasetId || "未选择"}</button>;
}

function RangeProbe() {
  const state = useAppState();
  return <div>
    <output>{[state.datasetId, state.start, state.end, state.rangeSource, state.rangeFact ?? "none", state.datasetRevision].join("|")}</output>
    <button onClick={() => state.setAutomaticRange("2025-08-01", "2025-08-31", "orders")}>订单推荐</button>
    <button onClick={() => state.setRange("2030-01-01", "2030-12-31")}>手动范围</button>
    <button onClick={() => state.setAutomaticRange("2013-02-01", "2014-01-28", "refunds")}>退款推荐</button>
    <button onClick={() => state.setDatasetId("dataset-next")}>切换数据集</button>
  </div>;
}

describe("core recovery contracts", () => {
  beforeEach(() => {
    const values = new Map<string, string>();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
        clear: () => values.clear(),
      },
    });
  });

  it("does not select demo-all on first startup and persists an explicit choice", () => {
    const first = render(<AppStateProvider><DatasetProbe /></AppStateProvider>);
    expect(screen.getByRole("button", { name: "未选择" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "未选择" }));
    expect(screen.getByRole("button", { name: "demo-all" })).toBeInTheDocument();
    first.unmount();

    render(<AppStateProvider><DatasetProbe /></AppStateProvider>);
    expect(screen.getByRole("button", { name: "demo-all" })).toBeInTheDocument();
  });

  it("preserves explicit ranges until AUTO is requested and resets stale range on dataset switch", () => {
    render(<AppStateProvider><RangeProbe /></AppStateProvider>);
    fireEvent.click(screen.getByRole("button", { name: "订单推荐" }));
    expect(screen.getByText(/2025-08-01\|2025-08-31\|AUTO\|orders/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "手动范围" }));
    expect(screen.getByText(/2030-01-01\|2030-12-31\|USER\|none/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "退款推荐" }));
    expect(screen.getByText(/2013-02-01\|2014-01-28\|AUTO\|refunds/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "切换数据集" }));
    expect(screen.getByText("dataset-next|||AUTO|none|1")).toBeInTheDocument();
  });

  it("renders evidence details when optional contract fields are missing", () => {
    render(<EvidenceDetail item={{ contract_version: "topic-evidence.v1", id: "ev-1", metric: "GMV", value: null }} />);
    expect(screen.getAllByText("数据不可用").length).toBeGreaterThan(1);
    expect(screen.getByText("当前证据未提供来源字段。")).toBeInTheDocument();
  });

  it("renders assistant Markdown headings, lists, tables, quotes and links", async () => {
    render(<ChatMessage role="assistant" content={"# 结论\n\n- 动作\n\n> 限制\n\n| 指标 | 值 |\n| --- | --- |\n| GMV | 10 |\n\n[证据](https://example.com)"} />);
    expect(await screen.findByRole("heading", { name: "结论" }, { timeout: 5_000 })).toBeInTheDocument();
    expect(screen.getByText("动作").closest("li")).not.toBeNull();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "证据" })).toHaveAttribute("target", "_blank");
    expect(screen.getByText("限制").closest("blockquote")).not.toBeNull();
  });
});
