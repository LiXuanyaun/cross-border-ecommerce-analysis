import ReactEChartsCore from "echarts-for-react/lib/core";
import type { ComponentProps } from "react";
import { BarChart, LineChart, PieChart, TreemapChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  TreemapChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

export type EChartProps = ComponentProps<typeof ReactEChartsCore>;

export function EChart(props: EChartProps) {
  return <ReactEChartsCore echarts={echarts} {...props} />;
}
