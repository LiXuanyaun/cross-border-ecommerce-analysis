import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import ReactECharts from "echarts-for-react";
import {
  BarChart3,
  Boxes,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Download,
  Eye,
  FileSearch,
  Lightbulb,
  PackageSearch,
  RefreshCcw,
  Search,
  ShoppingBag,
  Store,
  Undo2,
  Users,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, Button, Card, Drawer, EmptyState, ErrorState, Skeleton, cx } from "../components/ui";
import { api, queryString } from "../lib/api";
import { useAppState } from "../state/app";
import type {
  TopicAction,
  TopicColumn,
  TopicComposition,
  TopicData,
  TopicDecisionItem,
  TopicEvidence,
  TopicFinding,
  TopicMetric,
  TopicRanking,
  TopicReport,
  TopicValueFormat,
} from "../types";

const topicItems = [
  { id: "market", label: "市场", description: "规模与投入", icon: Store, color: "#1769ff" },
  { id: "product", label: "商品", description: "结构与效率", icon: ShoppingBag, color: "#7f56d9" },
  { id: "customer", label: "客户", description: "价值与分群", icon: Users, color: "#12b76a" },
  { id: "profit", label: "利润", description: "贡献与亏损", icon: CircleDollarSign, color: "#f79009" },
  { id: "returns", label: "退货", description: "风险与暴露", icon: Undo2, color: "#e5484d" },
] as const;

type TopicId = (typeof topicItems)[number]["id"];
type DetailState =
  | { type: "row"; row: Record<string, unknown> }
  | { type: "finding"; item: TopicFinding }
  | { type: "evidence"; item: TopicEvidence }
  | { type: "action"; item: TopicAction }
  | { type: "anomaly" | "driver"; item: TopicDecisionItem }
  | { type: "anomalies"; items: TopicDecisionItem[] }
  | null;

const topicSet = new Set<TopicId>(topicItems.map((item) => item.id));
const pageSizes = [10, 20, 50];

function topicConfig(topic: TopicId) {
  return topicItems.find((item) => item.id === topic)!;
}

function number(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatTopicValue(value: unknown, format: TopicValueFormat, categories?: Map<string, string>) {
  if (value === null || value === undefined || value === "") return "数据不可用";
  if (format === "text") return String(value);
  if (format === "category") return categories?.get(String(value)) ?? String(value);
  const numeric = number(value);
  if (numeric === null) return String(value);
  if (format === "currency") return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 }).format(numeric);
  if (format === "percent") return `${(numeric * 100).toFixed(1)}%`;
  if (format === "days") return `${numeric.toFixed(1)} 天`;
  if (format === "decimal") return numeric.toLocaleString("zh-CN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return numeric.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function compactValue(value: unknown, format: TopicValueFormat) {
  const numeric = number(value);
  if (numeric === null) return "-";
  if (format === "currency") return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", notation: "compact", maximumFractionDigits: 1 }).format(numeric);
  if (format === "percent") return `${(numeric * 100).toFixed(1)}%`;
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(numeric);
}

function changeText(value: number | null) {
  if (value === null) return "暂无可比月";
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}

export function AnalyticsPage() {
  const { datasetId, start: defaultStart, end: defaultEnd } = useAppState();
  const [params, setParams] = useSearchParams();
  const rawTopic = params.get("topic") as TopicId | null;
  const topic: TopicId = rawTopic && topicSet.has(rawTopic) ? rawTopic : "market";
  const start = params.get("start") ?? defaultStart;
  const end = params.get("end") ?? defaultEnd;
  const market = params.get("market") ?? "";
  const category = params.get("category") ?? "";
  const urlSearch = params.get("search") ?? "";
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const pageSize = pageSizes.includes(Number(params.get("page_size"))) ? Number(params.get("page_size")) : 20;
  const [searchInput, setSearchInput] = useState(urlSearch);
  const [detail, setDetail] = useState<DetailState>(null);
  const [reportOpen, setReportOpen] = useState(false);

  useEffect(() => {
    const next = new URLSearchParams(params);
    let changed = false;
    const defaults = { topic, start, end, page: String(page), page_size: String(pageSize) };
    Object.entries(defaults).forEach(([key, value]) => {
      if (!next.get(key)) {
        next.set(key, value);
        changed = true;
      }
    });
    if (changed) setParams(next, { replace: true });
  }, [end, page, pageSize, params, setParams, start, topic]);

  useEffect(() => setSearchInput(urlSearch), [urlSearch]);
  useEffect(() => {
    if (searchInput === urlSearch) return;
    const timer = window.setTimeout(() => {
      const next = new URLSearchParams(params);
      if (searchInput.trim()) next.set("search", searchInput.trim());
      else next.delete("search");
      next.set("page", "1");
      setParams(next, { replace: true });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [params, searchInput, setParams, urlSearch]);

  const update = (key: string, value: string, replace = false) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (!new Set(["page", "page_size", "search"]).has(key)) next.set("page", "1");
    if (key === "page_size") next.set("page", "1");
    setParams(next, { replace });
  };

  const switchTopic = (nextTopic: TopicId) => {
    const next = new URLSearchParams(params);
    next.set("topic", nextTopic);
    next.set("page", "1");
    next.delete("search");
    setSearchInput("");
    setParams(next);
  };

  const resetFilters = () => {
    setSearchInput("");
    setParams({ topic, start: defaultStart, end: defaultEnd, page: "1", page_size: String(pageSize) });
  };

  const query = useQuery({
    queryKey: ["topic", datasetId, topic, start, end, market, category, urlSearch, page, pageSize],
    queryFn: () => api<TopicData>(`/topics/${topic}${queryString({ dataset_id: datasetId, start, end, market, category, search: urlSearch, page, page_size: pageSize })}`),
  });

  const exportUrl = `/api/v1/topics/${topic}/export${queryString({ dataset_id: datasetId, start, end, market, category, search: urlSearch })}`;
  const active = topicConfig(topic);
  const topicData = query.data?.data;
  const categoryMap = useMemo(() => new Map((topicData?.filters.categories ?? []).map((item) => [item.value, item.label])), [topicData]);

  return (
    <div className="page-enter p-4 md:p-6">
      <div className="mb-4">
        <h1 className="text-[24px] font-semibold text-ink">专题分析</h1>
        <p className="mt-1 text-sm text-muted">{active.label} · {active.description}</p>
      </div>
      <div className="grid min-h-[calc(100vh-128px)] grid-cols-1 gap-4 xl:grid-cols-[142px_minmax(0,1fr)]">
        <TopicNavigation topic={topic} switchTopic={switchTopic} />
        <main className="min-w-0 space-y-4">
          <FilterBar start={start} end={end} market={market} category={category} data={topicData} update={update} reset={resetFilters} />
          {query.isLoading ? (
            <AnalyticsLoading />
          ) : query.isError ? (
            <ErrorState message={query.error.message} retry={() => query.refetch()} />
          ) : !topicData ? (
            <AnalyticsLoading />
          ) : (
            <>
              <SummaryBlock topic={topic} summary={topicData.summary} basis={topicData.decision_board.basis} />
              <MetricGrid metrics={topicData.metrics} color={active.color} />
              <DecisionBoard
                data={topicData}
                color={active.color}
                onDetail={(nextDetail) => setDetail(nextDetail)}
                onReport={() => setReportOpen(true)}
              />
              <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
                <CompositionChart topic={topic} data={topicData.composition} color={active.color} />
                <RankingChart topic={topic} data={topicData.ranking} color={active.color} />
              </div>
              <TopicTable
                data={topicData}
                page={page}
                pageSize={pageSize}
                search={searchInput}
                setSearch={setSearchInput}
                update={update}
                exportUrl={exportUrl}
                onView={(row) => setDetail({ type: "row", row })}
                categoryMap={categoryMap}
              />
            </>
          )}
        </main>
      </div>
      <Drawer open={detail !== null} onOpenChange={(open) => !open && setDetail(null)} title={detailTitle(detail, active.label)}>
        {detail && topicData && <DetailContent detail={detail} data={topicData} categoryMap={categoryMap} />}
      </Drawer>
      {topicData && (
        <ReportPreview
          open={reportOpen}
          onOpenChange={setReportOpen}
          report={topicData.report}
          metrics={topicData.metrics}
          exportUrl={exportUrl}
          color={active.color}
        />
      )}
    </div>
  );
}

function TopicNavigation({ topic, switchTopic }: { topic: TopicId; switchTopic: (topic: TopicId) => void }) {
  return (
    <Card className="h-fit p-2 xl:sticky xl:top-20">
      <h2 className="px-2 pb-2 pt-1 text-xs font-semibold text-muted">分析主题</h2>
      <div className="grid grid-cols-2 gap-1 sm:grid-cols-5 xl:grid-cols-1">
        {topicItems.map((item) => (
          <button
            key={item.id}
            onClick={() => switchTopic(item.id)}
            className={cx(
              "group flex min-h-12 items-center gap-2.5 rounded-md px-2 text-left transition hover:bg-[#f5f7fa] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30",
              topic === item.id && "bg-[#edf3ff] text-brand ring-1 ring-inset ring-brand/30",
            )}
          >
            <item.icon size={17} className="shrink-0" />
            <span className="min-w-0">
              <strong className="block text-sm font-medium">{item.label}</strong>
              <span className={cx("mt-0.5 hidden truncate text-[10px] xl:block", topic === item.id ? "text-brand/70" : "text-muted")}>{item.description}</span>
            </span>
          </button>
        ))}
      </div>
    </Card>
  );
}

function FilterBar({ start, end, market, category, data, update, reset }: { start: string; end: string; market: string; category: string; data?: TopicData; update: (key: string, value: string) => void; reset: () => void }) {
  return (
    <Card className="flex flex-wrap items-end gap-3 p-3">
      <DateField label="开始日期" value={start} onChange={(value) => update("start", value)} />
      <DateField label="结束日期" value={end} onChange={(value) => update("end", value)} />
      <label className="min-w-[132px] flex-1 text-[11px] text-muted">
        <span className="mb-1.5 block">市场</span>
        <select value={market} onChange={(event) => update("market", event.target.value)} className="h-9 w-full rounded-md border border-line bg-white px-2 text-xs text-ink outline-none focus:border-brand">
          <option value="">全部市场</option>
          {data?.filters.markets.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </label>
      <label className="min-w-[132px] flex-1 text-[11px] text-muted">
        <span className="mb-1.5 block">品类</span>
        <select value={category} onChange={(event) => update("category", event.target.value)} className="h-9 w-full rounded-md border border-line bg-white px-2 text-xs text-ink outline-none focus:border-brand">
          <option value="">全部品类</option>
          {data?.filters.categories.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </label>
      <Button variant="secondary" className="h-9 shrink-0" onClick={reset}><RefreshCcw size={15} />重置</Button>
    </Card>
  );
}

function DateField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="min-w-[138px] flex-1 text-[11px] text-muted">
      <span className="mb-1.5 block">{label}</span>
      <span className="relative block">
        <CalendarDays size={14} className="pointer-events-none absolute left-2.5 top-2.5" />
        <input type="date" value={value} onChange={(event) => onChange(event.target.value)} className="h-9 w-full rounded-md border border-line bg-white pl-8 pr-2 text-xs text-ink outline-none focus:border-brand" />
      </span>
    </label>
  );
}

function SummaryBlock({ topic, summary, basis }: { topic: TopicId; summary: string; basis: string }) {
  const Icon = topicConfig(topic).icon;
  return (
    <Card className="border-l-[3px] p-4" style={{ borderLeftColor: topicConfig(topic).color }}>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-md bg-[#f3f6fb]" style={{ color: topicConfig(topic).color }}><Icon size={17} /></span>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">本期摘要</h2>
          <p className="mt-1.5 text-sm leading-6 text-[#344054]">{summary}</p>
          <p className="mt-2 text-[11px] leading-5 text-muted">判断口径：{basis}</p>
        </div>
      </div>
    </Card>
  );
}

function MetricGrid({ metrics, color }: { metrics: TopicMetric[]; color: string }) {
  return <section aria-label="专题核心指标" className="grid grid-cols-1 gap-3 sm:grid-cols-2 2xl:grid-cols-4">{metrics.map((metric) => <TopicMetricCard key={metric.id} metric={metric} color={color} />)}</section>;
}

function TopicMetricCard({ metric, color }: { metric: TopicMetric; color: string }) {
  const positive = (metric.change ?? 0) >= 0;
  const rows = metric.sparkline.filter((item) => item.value !== null);
  const option: EChartsOption = {
    animationDuration: 300,
    grid: { left: 1, right: 1, top: 4, bottom: 2 },
    xAxis: { type: "category", show: false, data: rows.map((item) => item.label) },
    yAxis: { type: "value", show: false, scale: true },
    tooltip: { show: false },
    series: [{ type: "line", data: rows.map((item) => item.value), symbol: "none", smooth: 0.2, lineStyle: { width: 2, color } }],
  };
  return (
    <Card className="grid min-h-[102px] grid-cols-[minmax(0,1fr)_76px] items-center gap-2 p-3">
      <div className="min-w-0">
        <p className="text-xs text-muted">{metric.label}</p>
        <p className="mt-1.5 truncate text-xl font-semibold tabular-nums">{formatTopicValue(metric.value, metric.format)}</p>
        <p className={cx("mt-1.5 text-[11px] font-medium", metric.change === null ? "text-muted" : positive ? "text-success" : "text-danger")}>{changeText(metric.change)} <span className="font-normal text-muted">较前一月</span></p>
      </div>
      <ReactECharts option={option} style={{ width: 76, height: 42 }} notMerge lazyUpdate />
    </Card>
  );
}

function DecisionBoard({ data, color, onDetail, onReport }: { data: TopicData; color: string; onDetail: (detail: Exclude<DetailState, null>) => void; onReport: () => void }) {
  return (
    <section aria-label="经营判断板" className="space-y-4">
      <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,2fr)_minmax(340px,1fr)]">
        <ComparisonTrend data={data} color={color} />
        <AnomalyTable items={data.decision_board.anomalies} onView={(item) => onDetail({ type: "anomaly", item })} onViewAll={() => onDetail({ type: "anomalies", items: data.decision_board.anomalies })} />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-4">
        <FindingCard items={data.ai.findings} onView={(item) => onDetail({ type: "finding", item })} />
        <DriverCard items={data.decision_board.drivers} onView={(item) => onDetail({ type: "driver", item })} />
        <EvidenceCard items={data.ai.evidence} onView={(item) => onDetail({ type: "evidence", item })} />
        <ActionCard items={data.ai.actions} onView={(item) => onDetail({ type: "action", item })} onReport={onReport} />
      </div>
    </section>
  );
}

function ComparisonTrend({ data, color }: { data: TopicData; color: string }) {
  const trend = data.decision_board.trend;
  const option: EChartsOption = {
    animationDuration: 350,
    color: [color, "#c3cad5"],
    tooltip: {
      trigger: "axis",
      backgroundColor: "#fff",
      borderColor: "#e5e9f0",
      textStyle: { color: "#111827", fontSize: 11 },
      valueFormatter: (value) => formatTopicValue(value, trend.format),
    },
    legend: { top: 0, left: 0, itemWidth: 18, itemHeight: 3, textStyle: { color: "#667085", fontSize: 10 }, data: ["本期", "上期"] },
    grid: { left: 8, right: 12, top: 42, bottom: 8, containLabel: true },
    xAxis: { type: "category", boundaryGap: false, data: trend.rows.map((item) => item.label), axisLine: { lineStyle: { color: "#e5e9f0" } }, axisTick: { show: false }, axisLabel: { color: "#98a2b3", fontSize: 10 } },
    yAxis: { type: "value", scale: true, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: "#98a2b3", fontSize: 9, formatter: (value: number) => compactValue(value, trend.format) }, splitLine: { lineStyle: { color: "#edf0f4", type: "dashed" } } },
    series: [
      { name: "本期", type: "line", data: trend.rows.map((item) => item.current), symbolSize: 6, smooth: 0.2, lineStyle: { width: 2.5 } },
      { name: "上期", type: "line", data: trend.rows.map((item) => item.comparison), symbolSize: 5, smooth: 0.2, lineStyle: { width: 1.7, type: "dashed" } },
    ],
  };
  return (
    <Card className="h-[356px] p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><h2 className="text-sm font-semibold">{trend.title}</h2><p className="mt-1 text-[11px] text-muted">本期 {trend.current_period.start} 至 {trend.current_period.end} · 上期 {trend.comparison_period.start} 至 {trend.comparison_period.end}</p></div>
      </div>
      <ReactECharts option={option} style={{ height: 278 }} notMerge lazyUpdate />
    </Card>
  );
}

function AnomalyTable({ items, onView, onViewAll }: { items: TopicDecisionItem[]; onView: (item: TopicDecisionItem) => void; onViewAll: () => void }) {
  return (
    <Card className="flex h-[356px] min-w-0 flex-col overflow-hidden">
      <div className="px-4 pb-3 pt-4"><h2 className="text-sm font-semibold">异常对象（Top 5）</h2></div>
      <div className="min-h-0 flex-1 overflow-hidden">
        <table className="w-full table-fixed text-left text-[10px] sm:text-[11px]">
          <thead className="border-y border-line bg-[#fafbfc] text-muted"><tr><th className="w-[29%] px-2 py-2.5 font-medium sm:w-[34%] sm:px-4">对象</th><th className="w-[28%] px-1 py-2.5 text-right font-medium sm:w-[25%] sm:px-2">影响金额</th><th className="w-[23%] px-1 py-2.5 text-right font-medium sm:w-[20%] sm:px-2">影响占比</th><th className="w-[20%] px-2 py-2.5 text-right font-medium sm:w-[21%] sm:px-4">状态</th></tr></thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className="border-b border-line last:border-0">
                <td className="px-2 py-3 sm:px-4"><button className="max-w-full truncate font-medium text-ink hover:text-brand" onClick={() => onView(item)}>{item.object}</button></td>
                <td className={cx("px-1 py-3 text-right font-medium tabular-nums sm:px-2", item.impact_amount < 0 ? "text-danger" : "text-ink")}>{compactValue(item.impact_amount, "currency")}</td>
                <td className="px-1 py-3 text-right tabular-nums text-muted sm:px-2">{formatTopicValue(item.impact_share, "percent")}</td>
                <td className="px-2 py-3 text-right sm:px-4"><Badge tone={item.status === "需关注" ? "red" : "orange"} className="h-5 px-1 text-[9px] sm:px-1.5 sm:text-[10px]">{item.status}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button onClick={onViewAll} className="mx-4 mb-3 self-end text-[11px] font-medium text-brand hover:underline">查看全部异常对象</button>
    </Card>
  );
}

function BoardCard({ title, icon, children, footer }: { title: string; icon: React.ReactNode; children: React.ReactNode; footer?: React.ReactNode }) {
  return (
    <Card className="flex min-h-[258px] min-w-0 flex-col p-4">
      <div className="flex items-center gap-2">{icon}<h2 className="text-sm font-semibold">{title}</h2></div>
      <div className="mt-3 min-h-0 flex-1">{children}</div>
      {footer}
    </Card>
  );
}

function FindingCard({ items, onView }: { items: TopicFinding[]; onView: (item: TopicFinding) => void }) {
  return (
    <BoardCard title="关键发现" icon={<Lightbulb size={16} className="text-success" />}>
      <div className="space-y-3">{items.slice(0, 3).map((item, index) => <button key={item.id} onClick={() => onView(item)} className="group flex w-full items-start gap-2 text-left"><span className={cx("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", index === 0 ? "bg-success" : index === 1 ? "bg-danger" : "bg-warning")} /><span className="line-clamp-3 text-xs leading-5 text-[#344054] group-hover:text-brand">{item.finding}</span></button>)}</div>
    </BoardCard>
  );
}

function DriverCard({ items, onView }: { items: TopicDecisionItem[]; onView: (item: TopicDecisionItem) => void }) {
  const max = Math.max(...items.map((item) => Math.abs(item.impact_amount)), 1);
  return (
    <BoardCard title="驱动因素分析" icon={<BarChart3 size={16} className="text-brand" />}>
      <div className="space-y-3">{items.slice(0, 5).map((item) => <button key={item.id} onClick={() => onView(item)} className="grid w-full grid-cols-[72px_minmax(0,1fr)_auto] items-center gap-2 text-left text-[11px]"><span className="truncate text-[#344054]">{item.object}</span><span className="h-1.5 overflow-hidden rounded bg-[#eef1f5]"><span className="block h-full rounded bg-brand" style={{ width: `${Math.max(5, Math.abs(item.impact_amount) / max * 100)}%` }} /></span><strong className="whitespace-nowrap tabular-nums text-muted">{compactValue(item.impact_amount, "currency")}</strong></button>)}</div>
    </BoardCard>
  );
}

function EvidenceCard({ items, onView }: { items: TopicEvidence[]; onView: (item: TopicEvidence) => void }) {
  return (
    <BoardCard title="数据证据" icon={<FileSearch size={16} className="text-brand" />}>
      <div className="space-y-3">{items.slice(0, 3).map((item) => <button key={item.id} onClick={() => onView(item)} className="group flex w-full items-start gap-2 text-left"><span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded bg-[#f2f6fc] text-[10px] font-semibold text-brand">证</span><span className="line-clamp-3 text-xs leading-5 text-[#475467] group-hover:text-brand">{item.claim}</span></button>)}</div>
    </BoardCard>
  );
}

function ActionCard({ items, onView, onReport }: { items: TopicAction[]; onView: (item: TopicAction) => void; onReport: () => void }) {
  return (
    <BoardCard
      title="建议动作（优先级）"
      icon={<CheckCircle2 size={16} className="text-brand" />}
      footer={<button onClick={onReport} className="mt-3 self-end text-[11px] font-medium text-brand hover:underline">查看完整分析报告</button>}
    >
      <div className="space-y-3">{items.slice(0, 3).map((item, index) => <button key={item.id} onClick={() => onView(item)} className="group flex w-full items-start gap-2 text-left"><span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[#eef3fb] text-[10px] font-semibold text-[#475467]">{index + 1}</span><span className="line-clamp-2 text-xs font-medium leading-5 text-[#344054] group-hover:text-brand">{item.title}</span></button>)}</div>
    </BoardCard>
  );
}

function CompositionChart({ topic, data, color }: { topic: TopicId; data: TopicComposition; color: string }) {
  const palette = [color, "#12b76a", "#f79009", "#7f56d9", "#e5484d", "#06b6d4", "#98a2b3", "#84adff"];
  let series: EChartsOption["series"];
  if (topic === "product") {
    series = [{ type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false }, label: { show: true, color: "#fff", fontSize: 10, formatter: "{b}" }, itemStyle: { borderColor: "#fff", borderWidth: 2, gapWidth: 2 }, data: data.rows.map((item) => ({ name: item.name, value: item.chart_value })) }];
  } else if (topic === "profit") {
    series = [{ type: "bar", data: data.rows.map((item, index) => ({ value: item.value, itemStyle: { color: palette[index] } })), barWidth: 12, itemStyle: { borderRadius: 3 } }];
  } else {
    series = [{ type: "pie", radius: topic === "customer" ? ["24%", "72%"] : ["50%", "72%"], roseType: topic === "customer" ? "radius" : undefined, center: ["42%", "52%"], label: { show: false }, data: data.rows.map((item) => ({ name: item.name, value: item.chart_value })) }];
  }
  const option: EChartsOption = {
    color: palette,
    tooltip: { trigger: "item", valueFormatter: (value) => formatTopicValue(value, data.format) },
    grid: topic === "profit" ? { left: 90, right: 12, top: 8, bottom: 8 } : undefined,
    xAxis: topic === "profit" ? { type: "value", show: false } : undefined,
    yAxis: topic === "profit" ? { type: "category", inverse: true, data: data.rows.map((item) => item.name), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: "#475467", fontSize: 10 } } : undefined,
    series,
  };
  return (
    <Card className="min-h-[310px] p-4">
      <div className="flex items-center gap-2"><Boxes size={16} style={{ color }} /><h2 className="text-sm font-semibold">{data.title}</h2></div>
      <div className="mt-2 grid grid-cols-[minmax(0,1fr)_124px] items-center">
        <ReactECharts option={option} style={{ height: 236 }} notMerge lazyUpdate />
        <div className="space-y-2">{data.rows.slice(0, 6).map((item, index) => <div key={item.name} className="min-w-0 text-[10px]"><div className="flex items-center gap-1.5"><span className="h-2 w-2 shrink-0 rounded-sm" style={{ backgroundColor: palette[index] }} /><span className="truncate font-medium text-[#475467]">{item.name}</span></div><div className="mt-0.5 flex justify-between gap-2 pl-3.5 text-muted"><span>{item.share === null ? "不可计算" : `${(item.share * 100).toFixed(1)}%`}</span><span className="truncate tabular-nums">{compactValue(item.value, data.format)}</span></div></div>)}</div>
      </div>
    </Card>
  );
}

function RankingChart({ topic, data, color }: { topic: TopicId; data: TopicRanking; color: string }) {
  const max = Math.max(...data.rows.map((item) => Math.abs(item.value)), 1);
  return (
    <Card className="min-h-[310px] p-4">
      <div className="flex items-center gap-2"><PackageSearch size={16} style={{ color }} /><h2 className="text-sm font-semibold">{data.title}</h2></div>
      <div className="mt-4 space-y-3">{data.rows.map((item) => <div key={`${item.rank}-${item.name}`} className="grid grid-cols-[26px_minmax(0,1fr)_auto] items-center gap-3"><span className={cx("grid h-6 w-6 place-items-center rounded text-xs font-semibold", item.rank <= 3 ? "bg-[#edf4ff] text-brand" : "bg-[#f2f4f7] text-muted")}>{item.rank}</span><div className="min-w-0"><div className="flex items-center justify-between gap-3 text-xs"><span className="truncate font-medium">{item.name}</span><span className="text-muted">{item.secondary === null ? "" : formatTopicValue(item.secondary, data.secondary_format ?? "text")}</span></div><div className="mt-1.5 h-1.5 overflow-hidden rounded bg-[#eef1f5]"><div className="h-full rounded" style={{ width: `${Math.max(2, Math.abs(item.value) / max * 100)}%`, backgroundColor: color }} /></div></div><strong className={cx("whitespace-nowrap text-xs tabular-nums", topic === "profit" && item.value < 0 ? "text-danger" : "text-ink")}>{formatTopicValue(item.value, data.format)}</strong></div>)}</div>
    </Card>
  );
}

function TopicTable({ data, page, pageSize, search, setSearch, update, exportUrl, onView, categoryMap }: { data: TopicData; page: number; pageSize: number; search: string; setSearch: (value: string) => void; update: (key: string, value: string) => void; exportUrl: string; onView: (row: Record<string, unknown>) => void; categoryMap: Map<string, string> }) {
  const first = data.pagination.total ? (page - 1) * pageSize + 1 : 0;
  const last = Math.min(page * pageSize, data.pagination.total);
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-4">
        <div><h2 className="text-sm font-semibold">明细表</h2><p className="mt-1 text-xs text-muted">显示 {first}-{last}，共 {data.pagination.total.toLocaleString()} 条</p></div>
        <div className="flex flex-wrap items-center gap-2"><label className="flex h-8 items-center gap-2 rounded-md border border-line px-2 text-muted"><Search size={14} /><input aria-label="搜索明细" value={search} onChange={(event) => setSearch(event.target.value)} className="w-36 bg-transparent text-xs text-ink outline-none" /></label><a href={exportUrl} download className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-line bg-white px-2.5 text-xs font-medium text-ink transition hover:bg-[#f8fafc]"><Download size={14} />导出</a></div>
      </div>
      {data.details.length ? <DetailTable columns={data.columns} rows={data.details} onView={onView} categoryMap={categoryMap} /> : <EmptyState title="没有匹配的明细" description="当前筛选范围内没有匹配记录。" />}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-xs text-muted">
        <label className="inline-flex items-center gap-2">每页<select value={pageSize} onChange={(event) => update("page_size", event.target.value)} className="h-8 rounded-md border border-line bg-white px-2 text-ink outline-none">{pageSizes.map((size) => <option key={size} value={size}>{size}</option>)}</select>条</label>
        <div className="flex items-center gap-2"><span>第 {page} / {data.pagination.pages} 页</span><Button variant="ghost" className="h-8 w-8 p-0" disabled={page <= 1} onClick={() => update("page", String(page - 1))} aria-label="上一页"><ChevronLeft size={16} /></Button><Button variant="ghost" className="h-8 w-8 p-0" disabled={page >= data.pagination.pages} onClick={() => update("page", String(page + 1))} aria-label="下一页"><ChevronRight size={16} /></Button></div>
      </div>
    </Card>
  );
}

function DetailTable({ columns, rows, onView, categoryMap }: { columns: TopicColumn[]; rows: Array<Record<string, unknown>>; onView: (row: Record<string, unknown>) => void; categoryMap: Map<string, string> }) {
  return (
    <div className="overflow-x-auto"><table className="w-full min-w-[940px] text-left text-xs"><thead className="bg-[#fafbfc] text-muted"><tr>{columns.map((column) => <th key={column.key} className="whitespace-nowrap px-3 py-3 font-medium">{column.label}</th>)}<th className="sticky right-0 bg-[#fafbfc] px-3 py-3 text-right font-medium">操作</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${String(row[columns[0]?.key])}-${index}`} className="border-t border-line hover:bg-[#f8faff]">{columns.map((column) => <td key={column.key} className="max-w-[180px] truncate px-3 py-3 tabular-nums text-[#344054]">{formatTopicValue(row[column.key], column.format, categoryMap)}</td>)}<td className="sticky right-0 bg-white px-3 py-2 text-right"><button onClick={() => onView(row)} className="inline-flex h-7 items-center gap-1 rounded px-2 text-xs font-medium text-brand hover:bg-[#edf4ff]"><Eye size={13} />查看</button></td></tr>)}</tbody></table></div>
  );
}

function detailTitle(detail: DetailState, topicLabel: string) {
  if (!detail) return `${topicLabel}详情`;
  if (detail.type === "row") return `${topicLabel}明细`;
  if (detail.type === "finding") return "关键发现";
  if (detail.type === "evidence") return "数据证据";
  if (detail.type === "anomalies") return "全部异常对象";
  if (detail.type === "anomaly") return "异常对象";
  if (detail.type === "driver") return "驱动因素";
  return "建议动作";
}

function DetailContent({ detail, data, categoryMap }: { detail: Exclude<DetailState, null>; data: TopicData; categoryMap: Map<string, string> }) {
  if (detail.type === "row") return <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line">{data.columns.map((column) => <Info key={column.key} label={column.label} value={formatTopicValue(detail.row[column.key], column.format, categoryMap)} />)}</div>;
  if (detail.type === "finding") return <div className="space-y-4"><Badge tone={detail.item.priority === "P0" ? "red" : detail.item.priority === "P1" ? "orange" : "blue"}>{detail.item.priority}</Badge><h3 className="text-lg font-semibold">{detail.item.title}</h3><p className="text-sm leading-7 text-[#475467]">{detail.item.finding}</p></div>;
  if (detail.type === "evidence") return <div className="space-y-4"><h3 className="text-lg font-semibold">{detail.item.metric}</h3><div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line"><Info label="证据值" value={`${detail.item.value ?? "数据不可用"} ${detail.item.unit ?? ""}`} /><Info label="样本量" value={detail.item.sample_size.toLocaleString()} /><Info label="可信度" value={detail.item.confidence} /><Info label="证据编号" value={detail.item.id} /></div><Block title="这说明什么">{detail.item.claim}</Block><Block title="怎么算的">{detail.item.formula}</Block><Block title="用了哪些字段">{detail.item.source_fields}</Block></div>;
  if (detail.type === "anomalies") return <div className="divide-y divide-line rounded-md border border-line">{detail.items.map((item) => <div key={item.id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 p-3"><div className="min-w-0"><p className="truncate text-sm font-medium">{item.rank}. {item.object}</p><p className="mt-1 text-xs text-muted">较上期 {changeText(item.change_rate)} · 影响占比 {formatTopicValue(item.impact_share, "percent")}</p></div><div className="text-right"><p className={cx("text-sm font-semibold tabular-nums", item.impact_amount < 0 ? "text-danger" : "text-ink")}>{formatTopicValue(item.impact_amount, "currency")}</p><Badge tone={item.status === "需关注" ? "red" : "orange"} className="mt-1 h-5 px-1.5 text-[10px]">{item.status}</Badge></div></div>)}</div>;
  if (detail.type === "anomaly" || detail.type === "driver") return <div className="space-y-4"><h3 className="text-lg font-semibold">{detail.item.object}</h3><div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line"><Info label="本期值" value={detail.item.current_value === null ? "数据不可用" : detail.item.current_value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} /><Info label="上期值" value={detail.item.comparison_value === null ? "数据不可用" : detail.item.comparison_value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} /><Info label="变化" value={changeText(detail.item.change_rate)} /><Info label="影响金额" value={formatTopicValue(detail.item.impact_amount, "currency")} /><Info label="影响占比" value={formatTopicValue(detail.item.impact_share, "percent")} /><Info label="本期订单" value={detail.item.orders.toLocaleString()} /></div><Block title="判断">{detail.item.status === "需关注" ? "这项变化对本期结果造成不利影响，需要先核查变化来源。" : "这项变化幅度较大，建议结合订单结构确认原因。"}</Block></div>;
  if (detail.type === "action") return <div className="space-y-4"><h3 className="text-lg font-semibold">{detail.item.title}</h3><Block title="具体怎么做">{detail.item.action}</Block><div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line"><Info label="负责人" value={detail.item.owner} /><Info label="何时复盘" value={detail.item.validation_period} /></div></div>;
  return null;
}

function ReportPreview({ open, onOpenChange, report, metrics, exportUrl, color }: { open: boolean; onOpenChange: (open: boolean) => void; report: TopicReport; metrics: TopicMetric[]; exportUrl: string; color: string }) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/30" />
        <DialogPrimitive.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100%-32px)] max-w-[880px] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-panel border border-line bg-white shadow-2xl">
          <header className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-white px-5 py-4"><div><DialogPrimitive.Title className="text-lg font-semibold">完整分析报告</DialogPrimitive.Title><DialogPrimitive.Description className="mt-1 text-xs text-muted">{report.title}</DialogPrimitive.Description></div><DialogPrimitive.Close asChild><Button variant="ghost" className="h-8 w-8 p-0" aria-label="关闭报告预览"><X size={17} /></Button></DialogPrimitive.Close></header>
          <div className="p-5">
            <div className="flex flex-wrap justify-between gap-3 border-b border-line pb-4"><div><h2 className="text-xl font-semibold">{report.title}</h2><p className="mt-2 text-xs text-muted">{report.period.start} 至 {report.period.end} · {report.filters.market} · {report.filters.category}</p></div><p className="text-xs text-muted">生成时间 {new Date(report.generated_at).toLocaleString("zh-CN", { hour12: false })}</p></div>
            <section className="py-5"><h3 className="text-xs font-semibold text-muted">本期结论</h3><p className="mt-2 text-sm leading-7 text-[#344054]">{report.summary}</p></section>
            <section className="grid grid-cols-2 gap-3 border-y border-line py-5 md:grid-cols-4">{metrics.map((metric) => <div key={metric.id} className="border-l-2 pl-3" style={{ borderColor: color }}><p className="text-xs text-muted">{metric.label}</p><p className="mt-1.5 text-lg font-semibold">{formatTopicValue(metric.value, metric.format)}</p></div>)}</section>
            <div className="grid gap-5 py-5 md:grid-cols-3"><ReportSection title="关键发现">{report.findings.map((item) => <ReportItem key={item.id} title={item.title} text={item.finding} />)}</ReportSection><ReportSection title="数据证据">{report.evidence.map((item) => <ReportItem key={item.id} title={item.metric} text={item.claim} />)}</ReportSection><ReportSection title="建议动作">{report.actions.map((item) => <ReportItem key={item.id} title={item.title} text={item.action} />)}</ReportSection></div>
            <div className="flex justify-end border-t border-line pt-4"><a href={exportUrl} download className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-brand px-3 text-sm font-medium text-white hover:bg-[#075ce8]"><Download size={15} />导出当前明细</a></div>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function ReportSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h3 className="mb-2 text-xs font-semibold text-muted">{title}</h3>{children}</section>;
}

function ReportItem({ title, text }: { title: string; text: string }) {
  return <div className="border-b border-line py-2 last:border-0"><strong className="text-xs">{title}</strong><p className="mt-1 text-xs leading-5 text-muted">{text}</p></div>;
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="min-h-[74px] bg-white p-3"><p className="text-xs text-muted">{label}</p><p className="mt-2 break-words text-sm font-medium">{value}</p></div>;
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="rounded-md border border-line bg-[#fafbfc] p-4"><h4 className="text-xs font-semibold">{title}</h4><p className="mt-2 text-sm leading-6 text-[#475467]">{children}</p></div>;
}

function AnalyticsLoading() {
  return <div className="space-y-4"><Skeleton className="h-24" /><div className="grid grid-cols-2 gap-3 2xl:grid-cols-4"><Skeleton className="h-[102px]" /><Skeleton className="h-[102px]" /><Skeleton className="h-[102px]" /><Skeleton className="h-[102px]" /></div><div className="grid gap-4 2xl:grid-cols-[2fr_1fr]"><Skeleton className="h-[356px]" /><Skeleton className="h-[356px]" /></div><div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4"><Skeleton className="h-[258px]" /><Skeleton className="h-[258px]" /><Skeleton className="h-[258px]" /><Skeleton className="h-[258px]" /></div></div>;
}
