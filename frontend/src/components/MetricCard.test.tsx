import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MetricCard } from "./MetricCard";

describe("MetricCard", () => {
  it("formats currency and comparison", () => {
    render(<MetricCard metric={{ label: "GMV（成交总额）", value: 8450231, format: "currency", change: 0.125, tone: "blue" }}/>);
    expect(screen.getByText("GMV（成交总额）")).toBeInTheDocument();
    expect(screen.getByText("+12.5%")).toBeInTheDocument();
  });
});
