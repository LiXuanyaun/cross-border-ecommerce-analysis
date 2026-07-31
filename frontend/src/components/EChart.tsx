import { lazy, Suspense, useEffect, useState, type CSSProperties } from "react";
import type { EChartsOption } from "echarts";
import type { EChartProps } from "./EChartImpl";

const LazyEChart = lazy(() => import("./EChartImpl").then((module) => ({ default: module.EChart })));

export type { EChartProps, EChartsOption };

export function EChart(props: EChartProps) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setReady(true), 1_500);
    return () => window.clearTimeout(timer);
  }, []);
  const placeholder = <div aria-label="图表加载中" className="animate-pulse rounded-md bg-[#f2f4f7]" style={props.style as CSSProperties} />;
  if (!ready) return placeholder;
  return (
    <Suspense fallback={placeholder}>
      <LazyEChart {...props} />
    </Suspense>
  );
}
