import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Lightbulb,
  LineChart,
  ListChecks,
  Package,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useMemo, useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, queryString } from "../../lib/api";
import type {
  Kpi,
  OverviewCategory,
  OverviewData,
  OverviewInsight,
  OverviewMarket,
  OverviewMethodologyItem,
  OverviewOpportunity,
  OverviewPeriod,
  OverviewTask,
  OverviewTrend,
} from "../../types";
import { useAppState } from "../../state/app";
import {
  Badge,
  Button,
  Card,
  Drawer,
  ErrorState,
  Skeleton,
  cx,
} from "../../components/ui";
import { EChart, type EChartsOption } from "../../components/EChart";
import { formatChange, formatValue } from "../../lib/format";

type DrawerState =
  | { type: "task"; task: OverviewTask }
  | { type: "insight"; insight: OverviewInsight }
  | { type: "opportunity"; opportunity: OverviewOpportunity }
  | { type: "trend" }
  | { type: "markets" }
  | { type: "products" }
  | { type: "tasks" }
  | { type: "opportunities" }
  | { type: "insights" }
  | null;

const chartColors = ["#1769ff", "#12b76a", "#f79009", "#7f56d9", "#e5484d", "#06b6d4", "#98a2b3"];

const workflowLabels: Record<string, string> = {
  TODO: "待处理",
  IN_PROGRESS: "处理中",
  COMPLETED: "已完成",
  REVIEWED: "已复盘",
  CLOSED: "已关闭",
};

function dateText(period: OverviewPeriod) {
  return `${period.start} 至 ${period.end}`;
}

function shortPeriod(period: OverviewPeriod) {
  return `${period.start.slice(5)} ~ ${period.end.slice(5)}`;
}

function currency(value: number | null | undefined, compact = false) {
  if (value == null) return "数据不可用";
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: compact ? 1 : 0,
    notation: compact ? "compact" : "standard",
  }).format(value);
}

function percent(value: number | null | undefined, digits = 1) {
  if (value == null) return "数据不可用";
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
}

function shareText(value: number | null | undefined) {
  if (value == null) return "数据不可用";
  return `${(value * 100).toFixed(1)}%`;
}

function metricValue(value: number | null, metricId: string) {
  if (value == null) return "数据不可用";
  if (["gmv", "aov", "profit"].includes(metricId)) return currency(value);
  if (["profit_margin", "return_rate", "market_contribution", "product_contribution"].includes(metricId)) {
    return `${(value * 100).toFixed(1)}%`;
  }
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 }).format(value);
}

function impactText(task: OverviewTask) {
  if (task.impact_amount == null) return "无法量化";
  if (task.impact_type === "aov_change") return `${currency(task.impact_amount)} / 单`;
  if (task.impact_type.includes("_pp")) return `${task.impact_amount > 0 ? "+" : ""}${(task.impact_amount * 100).toFixed(1)} 个百分点`;
  return currency(task.impact_amount);
}

function priorityTone(priority: string): "red" | "orange" | "blue" | "green" | "neutral" {
  if (priority === "P0") return "red";
  if (priority === "P1") return "orange";
  if (priority === "P2") return "blue";
  return "neutral";
}

function workflowTone(status: string): "red" | "orange" | "blue" | "green" | "neutral" {
  if (status === "COMPLETED") return "green";
  if (status === "IN_PROGRESS" || status === "REVIEWED") return "blue";
  if (status === "CLOSED") return "orange";
  return "neutral";
}

export function OverviewPage() {
  const { datasetId, start, end, setAutomaticRange } = useAppState();
  const queryClient = useQueryClient();
  const [grain, setGrain] = useState<"day" | "week">("day");
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const [insightTab, setInsightTab] = useState<"sustainability" | "history" | "evidence">("sustainability");
  const [statusOverrides, setStatusOverrides] = useState<Record<string, string>>({});
  const [updatingTask, setUpdatingTask] = useState(false);
  const query = useQuery({
    queryKey: ["overview", datasetId, start, end],
    queryFn: () =>
      api<OverviewData>(
        `/overview${queryString({ dataset_id: datasetId, start, end })}`,
      ),
    enabled: Boolean(datasetId && (Boolean(start && end) || (!start && !end))),
  });

  if (query.isLoading) return <OverviewLoading />;
  if (query.isError) {
    return (
      <div className="p-6">
        <ErrorState message={query.error.message} retry={() => query.refetch()} />
      </div>
    );
  }

  const envelope = query.data!;
  const data = envelope.data;
  if (data.data_state && ["EMPTY", "OUT_OF_RANGE", "INSUFFICIENT_DATA", "FAILED", "FATAL"].includes(data.data_state)) {
    return <OverviewRangeNotice data={data} useAvailablePeriod={() => {
      const period = data.recommended_period;
      if (period) setAutomaticRange(period.start, period.end, "orders");
    }} />;
  }
  const quality = Number(envelope.meta.quality_score ?? 0);
  const updatedAt = String(envelope.meta.generated_at ?? "");
  const taskStatus = (task: OverviewTask) => statusOverrides[task.id] ?? task.status;
  const openInsight = (insight: OverviewInsight) => {
    setInsightTab("sustainability");
    setDrawer({ type: "insight", insight });
  };
  const markInProgress = async (task: OverviewTask) => {
    setUpdatingTask(true);
    try {
      if (envelope.meta.app_mode === "private") {
        await api(`/work-items/${task.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            workflow_status: "IN_PROGRESS",
            owner: task.owner,
            deadline: task.deadline ?? task.current_period?.end ?? data.current_period.end,
            result_note: "",
            review_result: "",
            close_reason: "",
            closed_by: "",
          }),
        });
        await queryClient.invalidateQueries({ queryKey: ["overview", datasetId, start, end] });
      }
      setStatusOverrides((current) => ({ ...current, [task.id]: "IN_PROGRESS" }));
    } finally {
      setUpdatingTask(false);
    }
  };

  const saveTask = async (task: OverviewTask, patch: Partial<OverviewTask>) => {
    setUpdatingTask(true);
    try {
      if (envelope.meta.app_mode === "private") {
        await api(`/work-items/${task.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            workflow_status: patch.status ?? task.status,
            owner: patch.owner ?? task.owner,
            deadline: patch.deadline ?? task.deadline,
            result_note: patch.result_note ?? task.result_note,
            review_result: patch.review_result ?? task.review_result,
            close_reason: patch.close_reason ?? task.close_reason,
            closed_by: patch.closed_by ?? task.closed_by,
            closed_at: patch.closed_at ?? task.closed_at,
          }),
        });
        await queryClient.invalidateQueries({ queryKey: ["overview", datasetId, start, end] });
      }
      if (patch.status) {
        setStatusOverrides((current) => ({ ...current, [task.id]: patch.status! }));
      }
    } finally {
      setUpdatingTask(false);
    }
  };

  return (
    <div className="page-enter p-4 md:p-6">
      <header className="mb-5 flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
        <div>
          <h1 className="text-[24px] font-semibold text-ink">经营总览</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted md:text-sm">
            <span className="inline-flex items-center gap-1.5">
              <Clock3 size={15} />
              更新时间 {updatedAt ? new Date(updatedAt).toLocaleString("zh-CN", { hour12: false }) : "数据生成中"}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <ShieldCheck size={16} />
              数据可信度 <strong className="font-semibold text-success">{quality.toFixed(0)}%</strong>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <CalendarDays size={15} />
              当前完整月 {dateText(data.current_period)}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted">
          <span className="h-px w-8 bg-line" />
          环比月 {dateText(data.comparison_period)}
        </div>
      </header>

      <section aria-label="核心经营指标" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {data.kpis.map((metric) => <OverviewKpiCard key={metric.id ?? metric.label} metric={metric} />)}
      </section>

      <section className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(390px,.9fr)]">
        <OperatingTrend
          trend={data.trends[grain]}
          methodology={data.methodology.trend}
          grain={grain}
          setGrain={setGrain}
          onDetails={() => setDrawer({ type: "trend" })}
        />
        <TodayTasks
          tasks={data.tasks}
          methodology={data.methodology.tasks}
          taskStatus={taskStatus}
          onTask={(task) => setDrawer({ type: "task", task })}
          onAll={() => setDrawer({ type: "tasks" })}
        />
      </section>

      <section className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[1.08fr_1.08fr_.84fr]">
        <MarketPerformance markets={data.markets} methodology={data.methodology.markets} onDetails={() => setDrawer({ type: "markets" })} />
        <ProductPerformance categories={data.categories} methodology={data.methodology.products} onDetails={() => setDrawer({ type: "products" })} />
        <GrowthOpportunities
          opportunities={data.opportunities}
          methodology={data.methodology.opportunities}
          onOpportunity={(opportunity) => setDrawer({ type: "opportunity", opportunity })}
          onAll={() => setDrawer({ type: "opportunities" })}
        />
      </section>

      <RecentInsights
        insights={data.insights}
        methodology={data.methodology.insights}
        onInsight={openInsight}
        onAll={() => setDrawer({ type: "insights" })}
      />

      <Drawer
        open={drawer !== null}
        onOpenChange={(open) => !open && setDrawer(null)}
        title={drawerTitle(drawer)}
      >
        {drawer && (
          <DrawerContent
            drawer={drawer}
            data={data}
            grain={grain}
            taskStatus={taskStatus}
            insightTab={insightTab}
            setInsightTab={setInsightTab}
            setDrawer={setDrawer}
            markInProgress={markInProgress}
            saveTask={saveTask}
            updatingTask={updatingTask}
            appMode={String(envelope.meta.app_mode ?? "demo")}
          />
        )}
      </Drawer>
    </div>
  );
}

function OverviewRangeNotice({ data, useAvailablePeriod }: { data: OverviewData; useAvailablePeriod: () => void }) {
  const selected = data.requested_period ?? data.selection_period;
  const available = data.available_periods?.map(item => `${item.start} 至 ${item.end}`).join("；") || "暂无可用时期";
  return <div className="page-enter p-4 md:p-6"><h1 className="text-[24px] font-semibold text-ink">经营总览</h1><section role="status" className="mt-5 border-l-4 border-[#f79009] bg-[#fffaeb] px-4 py-4 text-[#7a2e0e]"><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><h2 className="text-sm font-semibold">当前选择时期没有订单事实</h2><p className="mt-1 text-xs leading-5">选择时期：{selected.start || "未指定"} 至 {selected.end || "未指定"}</p><p className="break-words text-xs leading-5">可用时期：{available}</p></div>{data.recommended_period && <Button className="shrink-0" onClick={useAvailablePeriod}>使用可用时期</Button>}</div></section></div>;
}

function SectionTitle({ icon: Icon, title, action, onAction }: { icon: typeof LineChart; title: string; action: string; onAction: () => void }) {
  return (
    <div className="flex min-h-10 items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <Icon size={17} className="text-brand" />
        <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
      </div>
      <button onClick={onAction} className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:text-[#075ce8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30">
        {action}<ArrowRight size={14} />
      </button>
    </div>
  );
}

function MethodologyNote({ item, compact = false }: { item: OverviewMethodologyItem; compact?: boolean }) {
  return <div className={cx("rounded-md border border-[#e7ebf1] bg-[#f8fafc] text-[#667085]", compact ? "mt-3 px-2.5 py-2 text-[9px] leading-4" : "mt-2 px-3 py-2 text-[10px] leading-4")}><p><strong className="font-semibold text-[#475467]">口径：</strong>{item.basis}</p><p><strong className="font-semibold text-[#475467]">比较：</strong>{item.comparison}</p><p><strong className="font-semibold text-[#475467]">阈值：</strong>{item.threshold}</p></div>;
}

function OverviewKpiCard({ metric }: { metric: Kpi }) {
  const positive = (metric.change ?? 0) >= 0;
  const sparkline = (metric.sparkline ?? []).filter((item) => item.value != null);
  const tone = metric.tone ?? "blue";
  const accent = tone === "violet" ? "#7f56d9" : tone === "green" ? "#12b76a" : tone === "orange" ? "#f79009" : "#1769ff";
  const option: EChartsOption = {
    animationDuration: 450,
    grid: { left: 2, right: 2, top: 5, bottom: 3 },
    xAxis: { type: "category", show: false, data: sparkline.map((item) => item.label) },
    yAxis: { type: "value", show: false, scale: true },
    tooltip: { show: false },
    series: [{
      type: "line",
      data: sparkline.map((item) => item.value),
      symbol: "none",
      smooth: 0.25,
      lineStyle: { color: accent, width: 2 },
      areaStyle: { color: `${accent}18` },
    }],
  };
  return (
    <Card className="min-h-[168px] p-4">
      <div className="grid grid-cols-[minmax(0,1fr)_108px] items-center gap-3">
        <div className="min-w-0">
        <p className="text-sm text-muted">{metric.label}</p>
        <p className="mt-2 whitespace-nowrap text-[24px] font-semibold tabular-nums text-ink">{formatValue(metric.value, metric.format)}</p>
        <div className="mt-2 flex items-center gap-1.5 text-xs">
          <span className={cx("inline-flex items-center gap-1 font-semibold", positive ? "text-success" : "text-danger")}>
            {positive ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
            {formatChange(metric.change)}
          </span>
          <span className="text-muted">较对比期</span>
        </div>
        </div>
        <div className="min-w-0">
        <EChart option={option} style={{ width: 108, height: 54 }} notMerge lazyUpdate />
        <p className="mt-1 text-right text-[10px] text-[#98a2b3]">最近 {sparkline.length} 个完整月</p>
        </div>
      </div>
      <div className="mt-3 border-t border-line pt-2 text-[10px] leading-4 text-muted"><p><strong className="font-medium text-[#475467]">口径：</strong>{metric.basis}</p><p><strong className="font-medium text-[#475467]">阈值：</strong>{metric.threshold}</p></div>
    </Card>
  );
}

function OperatingTrend({ trend, methodology, grain, setGrain, onDetails }: { trend: OverviewTrend; methodology: OverviewMethodologyItem; grain: "day" | "week"; setGrain: (grain: "day" | "week") => void; onDetails: () => void }) {
  const option = useMemo<EChartsOption>(() => ({
    color: ["#1769ff", "#aeb8c8"],
    tooltip: {
      trigger: "axis",
      backgroundColor: "#fff",
      borderColor: "#e5e9f0",
      borderWidth: 1,
      textStyle: { color: "#111827", fontSize: 12 },
      valueFormatter: (value) => currency(Number(value)),
    },
    legend: { top: 2, right: 0, itemWidth: 18, itemHeight: 3, textStyle: { color: "#667085", fontSize: 11 } },
    grid: { left: 8, right: 12, top: 46, bottom: 8, containLabel: true },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: trend.rows.map((row) => row.label),
      axisLine: { lineStyle: { color: "#e5e9f0" } },
      axisTick: { show: false },
      axisLabel: { color: "#98a2b3", fontSize: 10, interval: grain === "day" ? 4 : 0 },
    },
    yAxis: {
      type: "value",
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: "#98a2b3", fontSize: 10, formatter: (value: number) => currency(value, true) },
      splitLine: { lineStyle: { color: "#edf0f4", type: "dashed" } },
    },
    series: [
      {
        name: `当前期 ${shortPeriod(trend.current_period)}`,
        type: "line",
        data: trend.rows.map((row) => row.current),
        symbol: "circle",
        symbolSize: 5,
        lineStyle: { width: 2.5 },
        areaStyle: { color: "rgba(23,105,255,.06)" },
      },
      {
        name: `对比期 ${shortPeriod(trend.comparison_period)}`,
        type: "line",
        data: trend.rows.map((row) => row.comparison),
        symbol: "none",
        lineStyle: { width: 1.5, type: "dashed" },
      },
    ],
  }), [grain, trend]);
  return (
    <Card className="min-h-[410px] p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <LineChart size={17} className="text-brand" />
          <h2 className="text-[15px] font-semibold">经营趋势</h2>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex h-8 rounded-md bg-[#f2f4f7] p-0.5" aria-label="趋势粒度">
            {(["day", "week"] as const).map((item) => (
              <button key={item} onClick={() => setGrain(item)} className={cx("min-w-12 rounded px-3 text-xs font-medium transition", grain === item ? "bg-white text-ink shadow-sm" : "text-muted hover:text-ink")}>
                {item === "day" ? "按日" : "按周"}
              </button>
            ))}
          </div>
          <button onClick={onDetails} className="inline-flex items-center gap-1 text-xs font-medium text-brand">查看详情<ArrowRight size={14} /></button>
        </div>
      </div>
      <MethodologyNote item={methodology} />
      <EChart option={option} style={{ height: 276 }} notMerge lazyUpdate />
    </Card>
  );
}

function TodayTasks({ tasks, methodology, taskStatus, onTask, onAll }: { tasks: OverviewTask[]; methodology: OverviewMethodologyItem; taskStatus: (task: OverviewTask) => string; onTask: (task: OverviewTask) => void; onAll: () => void }) {
  return (
    <Card className="min-h-[410px] p-4">
      <SectionTitle icon={ListChecks} title="今日待处理事项" action={`查看全部 ${tasks.length}`} onAction={onAll} />
      <MethodologyNote item={methodology} />
      <div className="mt-1 divide-y divide-line">
        {tasks.map((task) => (
          <button key={task.id} onClick={() => onTask(task)} className="group grid w-full grid-cols-[minmax(0,1fr)_auto] gap-3 py-3 text-left first:pt-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Badge tone={priorityTone(task.priority)}>{task.priority}</Badge>
                <span className="truncate text-sm font-semibold text-ink">{task.object}</span>
                <Badge tone={workflowTone(taskStatus(task))}>{workflowLabels[taskStatus(task)] ?? taskStatus(task)}</Badge>
              </div>
              <p className="mt-1.5 truncate text-xs text-[#475467]">{task.anomaly} · {task.metric_label} {percent(task.change_rate)}</p>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
                <span>影响金额 <strong className={cx("font-semibold", (task.impact_amount ?? 0) < 0 ? "text-danger" : "text-success")}>{impactText(task)}</strong></span>
                <span>目标阈值 <strong className="font-medium text-[#475467]">{task.target_threshold}</strong></span>
              </div>
            </div>
            <ChevronRight size={16} className="mt-1 text-[#b2bac7] transition group-hover:translate-x-0.5 group-hover:text-brand" />
          </button>
        ))}
      </div>
    </Card>
  );
}

function MarketPerformance({ markets, methodology, onDetails }: { markets: OverviewMarket[]; methodology: OverviewMethodologyItem; onDetails: () => void }) {
  const option: EChartsOption = {
    color: chartColors,
    tooltip: { trigger: "item", valueFormatter: (value) => currency(Number(value)) },
    series: [{
      type: "pie",
      radius: ["58%", "78%"],
      center: ["50%", "52%"],
      label: { show: false },
      data: markets.map((item) => ({ name: item.name, value: item.gmv })),
    }],
  };
  return (
    <Card className="min-h-[400px] p-4">
      <SectionTitle icon={CircleDollarSign} title="市场表现" action="查看详情" onAction={onDetails} />
      <MethodologyNote item={methodology} />
      <div className="mt-2 grid grid-cols-[132px_minmax(0,1fr)] items-center gap-3">
        <div>
          <EChart option={option} style={{ height: 140 }} />
          <p className="-mt-3 text-center text-[10px] text-muted">GMV 构成</p>
        </div>
        <div className="space-y-2.5">
          {markets.map((market, index) => (
            <div key={market.market} className="grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-2 text-xs">
              <span className={cx("grid h-[18px] w-[18px] place-items-center rounded text-[10px] font-semibold", index < 3 ? "bg-[#edf4ff] text-brand" : "bg-[#f2f4f7] text-muted")}>{market.rank}</span>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ backgroundColor: chartColors[index] }} /><span className="truncate font-medium">{market.name}</span></div>
                <p className="mt-0.5 text-[10px] text-muted">占比 {shareText(market.share)}</p>
              </div>
              <div className="text-right">
                <p className="font-medium tabular-nums">{currency(market.gmv, true)}</p>
                <p className={cx("mt-0.5 text-[10px] font-medium", (market.yoy ?? 0) >= 0 ? "text-success" : "text-danger")}>同比 {percent(market.yoy)}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

function ProductPerformance({ categories, methodology, onDetails }: { categories: OverviewCategory[]; methodology: OverviewMethodologyItem; onDetails: () => void }) {
  const option: EChartsOption = {
    color: chartColors,
    tooltip: { trigger: "item", valueFormatter: (value) => currency(Number(value)) },
    series: [{
      type: "pie",
      radius: ["52%", "76%"],
      center: ["50%", "50%"],
      label: { show: false },
      data: categories.map((item) => ({ name: item.name, value: item.gmv })),
    }],
  };
  return (
    <Card className="min-h-[400px] p-4">
      <SectionTitle icon={Package} title="商品表现" action="查看详情" onAction={onDetails} />
      <MethodologyNote item={methodology} />
      <div className="mt-2 grid grid-cols-[132px_minmax(0,1fr)] items-center gap-3">
        <EChart option={option} style={{ height: 166 }} />
        <div className="space-y-2">
          {categories.slice(0, 5).map((category, index) => (
            <div key={category.category} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 text-xs">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5"><span className="h-2 w-2 shrink-0 rounded-sm" style={{ backgroundColor: chartColors[index] }} /><span className="truncate font-medium">{category.name}</span><span className="text-[10px] text-muted">{shareText(category.share)}</span></div>
                <div className="mt-1 h-1 overflow-hidden rounded bg-[#eef1f5]"><div className="h-full rounded" style={{ width: `${(category.share ?? 0) * 100}%`, backgroundColor: chartColors[index] }} /></div>
              </div>
              <div className="text-right">
                <p className="font-medium tabular-nums">{currency(category.gmv, true)}</p>
                <p className={cx("text-[10px] font-medium", (category.change_rate ?? 0) >= 0 ? "text-success" : "text-danger")}>{percent(category.change_rate)}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 border-t border-line pt-3 text-[10px] text-muted">
        {categories.slice(5).map((category, index) => <span key={category.category} className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ backgroundColor: chartColors[index + 5] }} />{category.name} {shareText(category.share)}</span>)}
      </div>
    </Card>
  );
}

function GrowthOpportunities({ opportunities, methodology, onOpportunity, onAll }: { opportunities: OverviewOpportunity[]; methodology: OverviewMethodologyItem; onOpportunity: (opportunity: OverviewOpportunity) => void; onAll: () => void }) {
  return (
    <Card className="min-h-[400px] p-4">
      <SectionTitle icon={Sparkles} title="增长机会" action="查看详情" onAction={onAll} />
      <MethodologyNote item={methodology} />
      <div className="mt-1 divide-y divide-line">
        {opportunities.map((opportunity) => (
          <button key={opportunity.id} onClick={() => onOpportunity(opportunity)} className="group flex w-full items-start gap-3 py-3 text-left first:pt-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30">
            <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-md bg-[#edf4ff] text-brand"><Lightbulb size={16} /></span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center justify-between gap-2"><strong className="truncate text-sm font-semibold">{opportunity.object}</strong><strong className="whitespace-nowrap text-sm text-success">+{currency(opportunity.estimated_growth, true)}</strong></span>
              <span className="mt-1 block line-clamp-2 text-xs leading-5 text-muted">依据：{opportunity.basis}</span>
            </span>
            <ChevronRight size={15} className="mt-1 text-[#b2bac7] transition group-hover:translate-x-0.5 group-hover:text-brand" />
          </button>
        ))}
      </div>
    </Card>
  );
}

function RecentInsights({ insights, methodology, onInsight, onAll }: { insights: OverviewInsight[]; methodology: OverviewMethodologyItem; onInsight: (insight: OverviewInsight) => void; onAll: () => void }) {
  return (
    <Card className="mt-4 overflow-hidden">
      <div className="border-b border-line px-4 py-3">
        <div className="flex items-center justify-between"><div className="flex items-center gap-2"><Lightbulb size={17} className="text-brand" /><h2 className="text-[15px] font-semibold">最近经营洞察</h2></div><button onClick={onAll} className="inline-flex items-center gap-1 text-xs font-medium text-brand">查看全部洞察<ArrowRight size={14} /></button></div>
        <MethodologyNote item={methodology} />
      </div>
      <div className="relative divide-y divide-line before:absolute before:bottom-5 before:left-[114px] before:top-5 before:w-px before:bg-[#dfe5ed] max-md:before:left-[22px]">
        {insights.map((insight) => (
          <button key={insight.id} onClick={() => onInsight(insight)} className="group relative grid w-full grid-cols-[16px_minmax(0,1fr)] items-start gap-x-3 gap-y-2 px-4 py-4 text-left transition hover:bg-[#f9fbff] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand/30 md:grid-cols-[84px_20px_210px_minmax(0,1fr)_auto] md:items-center md:gap-3">
            <span className="hidden text-xs tabular-nums text-muted md:block">{insight.period.slice(0, 7)}</span>
            <span className={cx("relative z-10 ml-0.5 h-3 w-3 rounded-full border-[3px] border-white ring-1", insight.priority === "P0" ? "bg-danger ring-danger/30" : insight.priority === "P1" ? "bg-warning ring-warning/30" : "bg-brand ring-brand/30")} />
            <span className="min-w-0 md:-ml-0.5"><span className="block truncate text-sm font-semibold">{insight.object}</span><span className="mt-0.5 block text-xs text-muted">{insight.metric_label} · {insight.priority}</span></span>
            <span className="col-start-2 min-w-0 md:col-auto"><span className="block line-clamp-1 text-sm leading-5 text-[#475467]">{insight.finding}</span><span className="mt-1 block line-clamp-1 text-xs text-muted">{insight.sustainability.reason}</span></span>
            <span className="col-start-2 inline-flex items-center gap-2 md:col-auto"><Badge tone={insight.sustainability.level === "较强" ? "green" : insight.sustainability.level === "风险延续" ? "red" : "orange"}>可持续性 {insight.sustainability.level}</Badge><Badge tone="neutral">历史 {insight.history.similar_occurrences} 次</Badge><ChevronRight size={16} className="ml-auto text-[#b2bac7] transition group-hover:translate-x-0.5 group-hover:text-brand md:ml-0" /></span>
          </button>
        ))}
      </div>
    </Card>
  );
}

function drawerTitle(drawer: DrawerState) {
  if (!drawer) return "经营总览详情";
  const titles: Record<Exclude<DrawerState, null>["type"], string> = {
    task: "待处理事项详情",
    insight: "经营洞察详情",
    opportunity: "增长机会详情",
    trend: "经营趋势详情",
    markets: "市场表现详情",
    products: "商品表现详情",
    tasks: "全部待处理事项",
    opportunities: "全部增长机会",
    insights: "全部经营洞察",
  };
  return titles[drawer.type];
}

function DrawerContent({ drawer, data, grain, taskStatus, insightTab, setInsightTab, setDrawer, markInProgress, saveTask, updatingTask, appMode }: {
  drawer: Exclude<DrawerState, null>;
  data: OverviewData;
  grain: "day" | "week";
  taskStatus: (task: OverviewTask) => string;
  insightTab: "sustainability" | "history" | "evidence";
  setInsightTab: (tab: "sustainability" | "history" | "evidence") => void;
  setDrawer: (drawer: DrawerState) => void;
  markInProgress: (task: OverviewTask) => Promise<void>;
  saveTask: (task: OverviewTask, patch: Partial<OverviewTask>) => Promise<void>;
  updatingTask: boolean;
  appMode: string;
}) {
  if (drawer.type === "task") return <TaskDetail task={drawer.task} status={taskStatus(drawer.task)} onProgress={() => markInProgress(drawer.task)} onSave={(patch) => saveTask(drawer.task, patch)} updating={updatingTask} appMode={appMode} />;
  if (drawer.type === "insight") return <InsightDetail insight={drawer.insight} tab={insightTab} setTab={setInsightTab} />;
  if (drawer.type === "opportunity") return <OpportunityDetail opportunity={drawer.opportunity} />;
  if (drawer.type === "trend") return <TrendDetail trend={data.trends[grain]} />;
  if (drawer.type === "markets") return <MarketDetails markets={data.markets} period={data.current_period} comparison={data.market_comparison_period} />;
  if (drawer.type === "products") return <ProductDetails categories={data.categories} period={data.current_period} comparison={data.comparison_period} />;
  if (drawer.type === "tasks") return <DrawerList>{data.tasks.map((task) => <button key={task.id} onClick={() => setDrawer({ type: "task", task })} className="flex w-full items-center gap-3 border-b border-line py-3 text-left last:border-0"><Badge tone={priorityTone(task.priority)}>{task.priority}</Badge><span className="min-w-0 flex-1"><strong className="block truncate text-sm">{task.object}</strong><span className="mt-1 block truncate text-xs text-muted">{task.anomaly} · {impactText(task)}</span></span><ChevronRight size={16} className="text-muted" /></button>)}</DrawerList>;
  if (drawer.type === "opportunities") return <DrawerList>{data.opportunities.map((opportunity) => <button key={opportunity.id} onClick={() => setDrawer({ type: "opportunity", opportunity })} className="flex w-full items-center gap-3 border-b border-line py-3 text-left last:border-0"><span className="grid h-8 w-8 place-items-center rounded bg-[#edf4ff] text-brand"><Lightbulb size={16} /></span><span className="min-w-0 flex-1"><strong className="block truncate text-sm">{opportunity.object}</strong><span className="mt-1 block text-xs text-muted">预计增长 +{currency(opportunity.estimated_growth)}</span></span><ChevronRight size={16} className="text-muted" /></button>)}</DrawerList>;
  return <DrawerList>{data.insights.map((insight) => <button key={insight.id} onClick={() => { setInsightTab("sustainability"); setDrawer({ type: "insight", insight }); }} className="flex w-full items-center gap-3 border-b border-line py-3 text-left last:border-0"><span className="h-2.5 w-2.5 rounded-full bg-brand" /><span className="min-w-0 flex-1"><strong className="block truncate text-sm">{insight.object} · {insight.metric_label}</strong><span className="mt-1 block line-clamp-2 text-xs leading-5 text-muted">{insight.sustainability.reason}</span></span><Badge tone="neutral">历史 {insight.history.similar_occurrences} 次</Badge><ChevronRight size={16} className="text-muted" /></button>)}</DrawerList>;
}

function DrawerList({ children }: { children: React.ReactNode }) {
  return <div className="divide-y divide-line">{children}</div>;
}

function TaskDetail({ task, status, onProgress, onSave, updating, appMode }: { task: OverviewTask; status: string; onProgress: () => void; onSave: (patch: Partial<OverviewTask>) => Promise<void>; updating: boolean; appMode: string }) {
  const [form, setForm] = useState({
    status,
    owner: task.owner,
    deadline: task.deadline ?? "",
    result_note: task.result_note ?? "",
    review_result: task.review_result ?? "",
    close_reason: task.close_reason ?? "",
    closed_by: task.closed_by ?? "",
    closed_at: task.closed_at ?? "",
  });

  useEffect(() => {
    setForm({
      status,
      owner: task.owner,
      deadline: task.deadline ?? "",
      result_note: task.result_note ?? "",
      review_result: task.review_result ?? "",
      close_reason: task.close_reason ?? "",
      closed_by: task.closed_by ?? "",
      closed_at: task.closed_at ?? "",
    });
  }, [status, task]);

  return (
    <div className="space-y-5">
      <div><div className="flex items-center gap-2"><Badge tone={priorityTone(task.priority)}>{task.priority}</Badge><Badge tone={workflowTone(status)}>{workflowLabels[status] ?? status}</Badge></div><h3 className="mt-3 text-lg font-semibold">{task.object} · {task.anomaly}</h3><p className="mt-2 text-sm leading-6 text-muted">{task.finding}</p></div>
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line"><InfoCell label="影响金额" value={impactText(task)} tone={(task.impact_amount ?? 0) < 0 ? "danger" : "success"} /><InfoCell label="目标阈值" value={task.target_threshold} /><InfoCell label="当前值" value={metricValue(task.current_value, task.metric_id)} /><InfoCell label="对比值" value={metricValue(task.comparison_value, task.metric_id)} /></div>
      <DetailBlock title="诊断"><p>{task.diagnosis.summary}</p><p className="mt-2 text-xs text-muted">诊断状态 {task.diagnosis.status} · 可信度 {task.diagnosis.confidence_score.toFixed(0)}%</p></DetailBlock>
      <DetailBlock title="建议"><p>{task.recommendation.action}</p>{task.recommendation.stop_condition && <p className="mt-2 text-xs text-muted">停止条件：{task.recommendation.stop_condition}</p>}</DetailBlock>
      <DetailBlock title="责任与周期">
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-xs text-muted">状态
            <select value={form.status} onChange={(event) => setForm((current) => ({ ...current, status: event.target.value }))} className="mt-1 h-9 w-full rounded-md border border-line bg-white px-3 text-sm text-ink outline-none focus:border-brand">
              {Object.entries(workflowLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </label>
          <label className="text-xs text-muted">负责人
            <input value={form.owner} onChange={(event) => setForm((current) => ({ ...current, owner: event.target.value }))} className="mt-1 h-9 w-full rounded-md border border-line bg-white px-3 text-sm text-ink outline-none focus:border-brand" />
          </label>
          <label className="text-xs text-muted">截止日期
            <input type="date" value={form.deadline} onChange={(event) => setForm((current) => ({ ...current, deadline: event.target.value }))} className="mt-1 h-9 w-full rounded-md border border-line bg-white px-3 text-sm text-ink outline-none focus:border-brand" />
          </label>
          <label className="text-xs text-muted">关闭人
            <input value={form.closed_by} onChange={(event) => setForm((current) => ({ ...current, closed_by: event.target.value }))} className="mt-1 h-9 w-full rounded-md border border-line bg-white px-3 text-sm text-ink outline-none focus:border-brand" />
          </label>
        </div>
        <div className="mt-3 grid gap-3">
          <label className="text-xs text-muted">处理结果
            <textarea value={form.result_note} onChange={(event) => setForm((current) => ({ ...current, result_note: event.target.value }))} className="mt-1 min-h-20 w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none focus:border-brand" />
          </label>
          <label className="text-xs text-muted">复盘结论
            <textarea value={form.review_result} onChange={(event) => setForm((current) => ({ ...current, review_result: event.target.value }))} className="mt-1 min-h-20 w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none focus:border-brand" />
          </label>
          <label className="text-xs text-muted">关闭原因
            <textarea value={form.close_reason} onChange={(event) => setForm((current) => ({ ...current, close_reason: event.target.value }))} className="mt-1 min-h-20 w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none focus:border-brand" />
          </label>
          <label className="text-xs text-muted">关闭时间
            <input type="datetime-local" value={form.closed_at} onChange={(event) => setForm((current) => ({ ...current, closed_at: event.target.value }))} className="mt-1 h-9 w-full rounded-md border border-line bg-white px-3 text-sm text-ink outline-none focus:border-brand" />
          </label>
        </div>
        {task.current_period && <p className="mt-2 text-xs text-muted">当前周期：{dateText(task.current_period)}</p>}
        {task.comparison_period && <p className="mt-1 text-xs text-muted">对比周期：{dateText(task.comparison_period)}</p>}
      </DetailBlock>
      <div className="grid grid-cols-2 gap-2">
        <Button className="w-full" variant="secondary" onClick={onProgress} disabled={updating || status === "IN_PROGRESS"}>{status === "IN_PROGRESS" ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}{status === "IN_PROGRESS" ? "已标记处理中" : updating ? "正在更新" : "标记处理中"}</Button>
        <Button className="w-full" onClick={() => onSave({
          status: form.status as OverviewTask["status"],
          owner: form.owner,
          deadline: form.deadline || null,
          result_note: form.result_note,
          review_result: form.review_result,
          close_reason: form.close_reason,
          closed_by: form.closed_by,
          closed_at: form.closed_at || null,
        })} disabled={updating}>保存复盘</Button>
      </div>
      {appMode !== "private" && status === "IN_PROGRESS" && <p className="text-center text-xs text-muted">状态已更新到当前浏览会话</p>}
    </div>
  );
}

function InsightDetail({ insight, tab, setTab }: { insight: OverviewInsight; tab: "sustainability" | "history" | "evidence"; setTab: (tab: "sustainability" | "history" | "evidence") => void }) {
  return (
    <div>
      <div className="flex items-center gap-2"><Badge tone={priorityTone(insight.priority)}>{insight.priority}</Badge><Badge tone={insight.sustainability.level === "较强" ? "green" : insight.sustainability.level === "风险延续" ? "red" : "orange"}>可持续性 {insight.sustainability.level}</Badge></div>
      <h3 className="mt-3 text-lg font-semibold">{insight.object} · {insight.metric_label}</h3>
      <p className="mt-2 text-sm leading-6 text-muted">{insight.finding}</p>
      <div className="mt-5 grid grid-cols-3 rounded-md bg-[#f2f4f7] p-1">
        {(["sustainability", "history", "evidence"] as const).map((item) => <button key={item} onClick={() => setTab(item)} className={cx("h-8 rounded text-xs font-medium", tab === item ? "bg-white text-ink shadow-sm" : "text-muted")}>{item === "sustainability" ? "持续性" : item === "history" ? "历史模式" : "证据与建议"}</button>)}
      </div>
      <div className="mt-4">
        {tab === "sustainability" && <div className="space-y-3"><DetailBlock title="持续性判断"><p>{insight.sustainability.reason}</p></DetailBlock><div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line"><InfoCell label="连续同向周期" value={`${insight.sustainability.same_direction_periods} 个`} /><InfoCell label="本期变化" value={percent(insight.change_rate)} tone={(insight.change_rate ?? 0) < 0 ? "danger" : "success"} /><InfoCell label="利润率护栏" value={insight.sustainability.profit_margin_guardrail ? "通过" : "未通过"} tone={insight.sustainability.profit_margin_guardrail ? "success" : "danger"} /><InfoCell label="退货率护栏" value={insight.sustainability.return_rate_guardrail ? "通过" : "未通过"} tone={insight.sustainability.return_rate_guardrail ? "success" : "danger"} /></div></div>}
        {tab === "history" && <div className="space-y-3"><div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line"><InfoCell label="历史回看" value={`${insight.history.lookback_months} 个完整月`} /><InfoCell label="同类模式" value={`${insight.history.similar_occurrences} 次`} /></div><DetailBlock title="同类规则历史周期">{insight.history.similar_periods.length ? insight.history.similar_periods.map((item) => <div key={item.period} className="flex justify-between border-b border-line py-2 text-sm last:border-0"><span>{item.period.slice(0, 7)}</span><strong className={(item.change_rate ?? 0) < 0 ? "text-danger" : "text-success"}>{percent(item.change_rate)}</strong></div>) : <p>近12个完整月未发现同类规则命中。</p>}</DetailBlock><DetailBlock title="最近变化方向">{insight.history.recent_changes.map((item) => <div key={item.period} className="flex justify-between border-b border-line py-2 text-sm last:border-0"><span>{item.period.slice(0, 7)}</span><span>{percent(item.change_rate)}</span></div>)}</DetailBlock></div>}
        {tab === "evidence" && <div className="space-y-3"><DetailBlock title="证据来源"><p>{insight.evidence.formula}</p><p className="mt-2 text-xs text-muted">聚合记录 {insight.evidence.row_count?.toLocaleString()} 行 · 数据质量 {insight.evidence.quality_level} 级</p><p className="mt-2 break-all text-xs text-brand">{insight.evidence.ids.join(" · ")}</p></DetailBlock><DetailBlock title="建议动作"><p>{insight.recommendation.action}</p><p className="mt-2 text-xs text-muted">验证周期：{insight.recommendation.validation_period}</p><p className="mt-1 text-xs text-muted">停止条件：{insight.recommendation.stop_condition}</p></DetailBlock></div>}
      </div>
    </div>
  );
}

function OpportunityDetail({ opportunity }: { opportunity: OverviewOpportunity }) {
  return <div className="space-y-4"><div><Badge tone="green">{opportunity.status}</Badge><h3 className="mt-3 text-lg font-semibold">{opportunity.object}</h3><p className="mt-2 text-sm leading-6 text-muted">{opportunity.basis}</p></div><div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line"><InfoCell label="预计增长" value={`+${currency(opportunity.estimated_growth)}`} tone="success" /><InfoCell label="增长率" value={percent(opportunity.growth_rate)} tone="success" /><InfoCell label="当前 GMV" value={currency(opportunity.current_gmv)} /><InfoCell label="对比期 GMV" value={currency(opportunity.previous_gmv)} /></div><DetailBlock title="建议动作"><p>{opportunity.recommended_action}</p></DetailBlock><DetailBlock title="验证边界"><p>验证周期：{opportunity.validation_period}</p><p className="mt-2">停止条件：{opportunity.stop_condition}</p></DetailBlock><DetailBlock title="数据周期"><p>当前期：{opportunity.current_period}</p><p className="mt-2">对比期：{opportunity.comparison_period}</p></DetailBlock></div>;
}

function TrendDetail({ trend }: { trend: OverviewTrend }) {
  const current = trend.rows.reduce((sum, item) => sum + (item.current ?? 0), 0);
  const comparison = trend.rows.reduce((sum, item) => sum + (item.comparison ?? 0), 0);
  return <div className="space-y-4"><div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line"><InfoCell label="当前期 GMV" value={currency(current)} /><InfoCell label="对比期 GMV" value={currency(comparison)} /><InfoCell label="实际增减" value={currency(current - comparison)} tone={current >= comparison ? "success" : "danger"} /><InfoCell label="变化率" value={percent((current - comparison) / Math.abs(comparison || 1))} tone={current >= comparison ? "success" : "danger"} /></div><DetailBlock title="当前周期"><p>{dateText(trend.current_period)}</p></DetailBlock><DetailBlock title="对比周期"><p>{dateText(trend.comparison_period)}</p></DetailBlock><div className="divide-y divide-line rounded-md border border-line">{trend.rows.map((row) => <div key={row.current_date} className="grid grid-cols-3 gap-2 px-3 py-2 text-xs"><span className="text-muted">{row.current_date}</span><span className="text-right">{currency(row.current, true)}</span><span className="text-right text-muted">对比 {currency(row.comparison, true)}</span></div>)}</div></div>;
}

function MarketDetails({ markets, period, comparison }: { markets: OverviewMarket[]; period: OverviewPeriod; comparison: OverviewPeriod }) {
  return <div className="space-y-4"><DetailBlock title="同比周期"><p>当前：{dateText(period)}</p><p className="mt-2">去年同期：{dateText(comparison)}</p></DetailBlock><div className="divide-y divide-line rounded-md border border-line">{markets.map((market) => <div key={market.market} className="grid grid-cols-[28px_1fr_auto] items-center gap-3 px-3 py-3"><span className="grid h-6 w-6 place-items-center rounded bg-[#edf4ff] text-xs font-semibold text-brand">{market.rank}</span><div><p className="text-sm font-medium">{market.name}</p><p className="mt-1 text-xs text-muted">GMV 占比 {shareText(market.share)}</p></div><div className="text-right"><p className="text-sm font-semibold">{currency(market.gmv)}</p><p className={cx("mt-1 text-xs", (market.yoy ?? 0) >= 0 ? "text-success" : "text-danger")}>同比 {percent(market.yoy)}</p></div></div>)}</div></div>;
}

function ProductDetails({ categories, period, comparison }: { categories: OverviewCategory[]; period: OverviewPeriod; comparison: OverviewPeriod }) {
  return <div className="space-y-4"><DetailBlock title="对比周期"><p>当前：{dateText(period)}</p><p className="mt-2">对比：{dateText(comparison)}</p></DetailBlock><div className="divide-y divide-line rounded-md border border-line">{categories.map((category, index) => <div key={category.category} className="grid grid-cols-[12px_1fr_auto] items-center gap-3 px-3 py-3"><span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: chartColors[index] }} /><div><p className="text-sm font-medium">{category.name}</p><p className="mt-1 text-xs text-muted">占比 {shareText(category.share)}</p></div><div className="text-right"><p className="text-sm font-semibold">{currency(category.gmv)}</p><p className={cx("mt-1 text-xs", (category.change_rate ?? 0) >= 0 ? "text-success" : "text-danger")}>{percent(category.change_rate)}</p></div></div>)}</div></div>;
}

function DetailBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="rounded-md border border-line bg-[#fafbfc] p-4 text-sm leading-6 text-[#475467]"><h4 className="mb-2 text-xs font-semibold text-ink">{title}</h4>{children}</div>;
}

function InfoCell({ label, value, tone }: { label: string; value: string; tone?: "success" | "danger" }) {
  return <div className="min-h-[76px] bg-white p-3"><p className="text-xs text-muted">{label}</p><p className={cx("mt-2 break-words text-sm font-semibold", tone === "success" ? "text-success" : tone === "danger" ? "text-danger" : "text-ink")}>{value}</p></div>;
}

function OverviewLoading() {
  return (
    <div className="p-6">
      <Skeleton className="h-10 w-52" />
      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">{[1, 2, 3, 4].map((item) => <Skeleton key={item} className="h-[126px]" />)}</div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[1.65fr_.9fr]"><Skeleton className="h-[360px]" /><Skeleton className="h-[360px]" /></div>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">{[1, 2, 3].map((item) => <Skeleton key={item} className="h-[330px]" />)}</div>
    </div>
  );
}
