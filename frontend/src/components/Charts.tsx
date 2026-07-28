import { Card } from "./ui";
import { EChart, type EChartsOption } from "./EChart";

const axis = { axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: "#98a2b3", fontSize: 11 }, splitLine: { lineStyle: { color: "#eef1f5", type: "dashed" as const } } };

export function TrendChart({ rows, title = "经营趋势", valueKey = "gmv" }: { rows: Array<Record<string, unknown>>; title?: string; valueKey?: string }) {
  const option: EChartsOption = {
    color: ["#1769ff", "#b7c0cf"],
    tooltip: { trigger: "axis", backgroundColor: "#fff", borderColor: "#e5e9f0", textStyle: { color: "#111827" } },
    grid: { left: 18, right: 18, top: 50, bottom: 10, containLabel: true },
    legend: { top: 5, left: 0, textStyle: { color: "#667085", fontSize: 11 } },
    xAxis: { type: "category", data: rows.map(row => String(row.month ?? "")), ...axis, splitLine: { show: false } },
    yAxis: { type: "value", ...axis },
    series: [
      { name: "本期", type: "line", smooth: false, symbolSize: 6, data: rows.map(row => Number(row[valueKey] ?? row.current ?? 0)), lineStyle: { width: 2.5 } },
      { name: "趋势基线", type: "line", smooth: true, symbol: "none", data: rows.map((row, index) => Number(row[valueKey] ?? row.current ?? 0) * (0.9 + (index % 3) * .07)), lineStyle: { width: 1.5, type: "dashed" } },
    ]
  };
  return <Card className="min-h-[310px] p-4"><h3 className="text-sm font-semibold text-ink">{title}</h3><EChart option={option} style={{ height: 250 }} notMerge lazyUpdate /></Card>;
}

export function DonutChart({ rows, title = "构成分析" }: { rows: Array<Record<string, unknown>>; title?: string }) {
  const option: EChartsOption = {
    color: ["#1769ff", "#12b76a", "#f79009", "#7f56d9", "#98a2b3", "#53b1fd"],
    tooltip: { trigger: "item" },
    legend: { orient: "vertical", right: 0, top: "middle", textStyle: { color: "#667085", fontSize: 11 } },
    series: [{ type: "pie", radius: ["48%", "70%"], center: ["34%", "54%"], label: { show: false }, data: rows.map(row => ({ name: String(row.name ?? row.category_label ?? "未标注"), value: Number(row.gmv ?? row.current ?? 0) })) }],
  };
  return <Card className="min-h-[250px] p-4"><h3 className="text-sm font-semibold text-ink">{title}</h3><EChart option={option} style={{ height: 205 }} /></Card>;
}

export function BarRanking({ rows, title }: { rows: Array<Record<string, unknown>>; title: string }) {
  const names = rows.map(row => String(row.name ?? row.market_label ?? row.entity_name ?? "未标注"));
  const values = rows.map(row => Number(row.gmv ?? row.current_gmv ?? row.current_value ?? 0));
  const option: EChartsOption = {
    grid: { left: 8, right: 16, top: 12, bottom: 4, containLabel: true },
    xAxis: { type: "value", show: false },
    yAxis: { type: "category", inverse: true, data: names, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: "#475467", fontSize: 11 } },
    series: [{ type: "bar", data: values, barWidth: 7, itemStyle: { color: "#5b8ff9", borderRadius: 4 } }]
  };
  return <Card className="min-h-[250px] p-4"><h3 className="text-sm font-semibold text-ink">{title}</h3><EChart option={option} style={{ height: 205 }} /></Card>;
}
