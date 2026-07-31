import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Database, Eye, FileSearch, Lightbulb, Megaphone, RefreshCcw, Truck, Undo2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge, Button, Card, Drawer, EmptyState, ErrorState, Skeleton, cx } from "../../components/ui";
import { EChart, type EChartsOption } from "../../components/EChart";
import { api, queryString } from "../../lib/api";
import { useAppState } from "../../state/app";
import type { BusinessAnomaly, BusinessDataset, BusinessEvidence, BusinessMetric, BusinessTopic, BusinessTopicData } from "../../types";

const topics = [
  { id: "advertising", label: "广告分析", icon: Megaphone, accent: "#1769ff", description: "投放效率与归因收入" },
  { id: "returns", label: "退款分析", icon: Undo2, accent: "#e5484d", description: "退货原因与退款风险" },
  { id: "logistics", label: "物流分析", icon: Truck, accent: "#0e9384", description: "运输时效与轨迹异常" },
] as const;
const validTopics = new Set<BusinessTopic>(topics.map((item) => item.id));
const filterLabels: Record<string, string> = { country: "国家", channel: "渠道", platform: "平台", campaign_id: "活动", category: "品类", return_reason: "退货原因", carrier_id: "承运商", region: "地区" };
const detailLabels: Record<string, string> = { period: "周期", campaign_name: "广告活动", channel: "渠道", platform: "平台", spend_usd: "广告花费", attributed_revenue_usd: "归因收入", product_name: "商品", return_reason: "退货原因", refund_amount_usd: "退款金额", return_quantity: "退货数量", carrier_name: "承运商", destination_country: "目的国", transit_days: "运输天数", delay_hours: "延误小时" };
const detailColumns: Record<BusinessTopic, string[]> = {
  advertising: ["period", "campaign_name", "channel", "platform", "spend_usd", "attributed_revenue_usd"],
  returns: ["period", "product_name", "return_reason", "return_quantity", "refund_amount_usd"],
  logistics: ["period", "carrier_name", "destination_country", "transit_days", "delay_hours"],
};

function config(topic: BusinessTopic) { return topics.find((item) => item.id === topic)!; }
function formatValue(value: number | null | undefined, format: BusinessMetric["format"] = "decimal") {
  if (value === null || value === undefined || Number.isNaN(value)) return "数据不足";
  if (format === "currency") return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
  if (format === "percent") return `${(value * 100).toFixed(1)}%`;
  if (format === "days") return `${value.toFixed(1)} 天`;
  if (format === "integer") return Math.round(value).toLocaleString("zh-CN");
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}
function compact(value: unknown) { const number = Number(value); return Number.isFinite(number) ? new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(number) : "-"; }
function chartValue(value: unknown): string | number | null { return typeof value === "string" || typeof value === "number" ? value : null; }

export function BusinessAnalysisPage() {
  const route = useParams();
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const rawTopic = route.topic as BusinessTopic | undefined;
  const topic = rawTopic && validTopics.has(rawTopic) ? rawTopic : "advertising";
  const pageConfig = config(topic);
  const { datasetId, datasetRevision, start: defaultStart, end: defaultEnd, rangeSource, setRange, setAutomaticRange } = useAppState();
  const [detail, setDetail] = useState<{ title: string; body: React.ReactNode } | null>(null);
  const handledDatasetRevision = useRef(0);
  useEffect(() => { if (!rawTopic || !validTopics.has(rawTopic)) navigate("/business/advertising", { replace: true }); }, [navigate, rawTopic]);
  useEffect(() => {
    if (!datasetRevision || handledDatasetRevision.current === datasetRevision) return;
    handledDatasetRevision.current = datasetRevision;
    setSearch(new URLSearchParams(), { replace: true });
  }, [datasetRevision, setSearch]);

  const datasets = useQuery({
    queryKey: ["business-datasets"],
    queryFn: () => api<BusinessDataset[]>("/business/datasets").then((result) => result.data),
    staleTime: 5 * 60_000,
    refetchOnMount: false,
  });
  const selectedDataset = datasets.data?.find(item => item.dataset_id === datasetId);
  const filters = useMemo(() => {
    const values: Record<string, string> = {};
    ["start", "end", "country", "channel", "platform", "campaign_id", "category", "return_reason", "carrier_id", "region"].forEach((key) => { const value = search.get(key); if (value) values[key] = value; });
    if (defaultStart && (rangeSource === "AUTO" || !values.start)) values.start = defaultStart;
    if (defaultEnd && (rangeSource === "AUTO" || !values.end)) values.end = defaultEnd;
    return values;
  }, [defaultEnd, defaultStart, rangeSource, search]);
  const analysis = useQuery({
    queryKey: ["business-topic", topic, datasetId, filters, search.get("page"), search.get("page_size")],
    queryFn: () => api<BusinessTopicData>(`/business/${topic}${queryString({ dataset_id: datasetId, ...filters, page: search.get("page") ?? "1", page_size: search.get("page_size") ?? "20" })}`).then((result) => result.data),
    enabled: Boolean(datasetId && (Boolean(filters.start && filters.end) || (!filters.start && !filters.end))),
  });
  useEffect(() => {
    if (!analysis.data) return;
    const next = new URLSearchParams(search);
    let changed = false;
    Object.entries(analysis.data.filter_options).forEach(([key, options]) => {
      const selected = next.get(key);
      if (selected && !options.includes(selected)) { next.delete(key); changed = true; }
    });
    if (changed) { next.set("page", "1"); setSearch(next, { replace: true }); }
  }, [analysis.data, search, setSearch]);
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(search);
    if (value) next.set(key, value); else next.delete(key);
    next.set("page", "1");
    setSearch(next);
    if (key === "start" || key === "end") {
      setRange(key === "start" ? value : filters.start ?? "", key === "end" ? value : filters.end ?? "");
    }
  };
  const reset = () => setSearch(new URLSearchParams());
  const useRecommendedPeriod = () => {
    const period = analysis.data?.recommended_period;
    if (!period) return;
    const next = new URLSearchParams(search);
    next.delete("start");
    next.delete("end");
    next.set("page", "1");
    const fact = topic === "returns" ? "refunds" : topic;
    setAutomaticRange(period.start, period.end, fact);
    setSearch(next);
  };
  const topicHref = (nextTopic: BusinessTopic) => {
    const next = new URLSearchParams();
    if (rangeSource === "USER" && defaultStart && defaultEnd) {
      next.set("start", defaultStart);
      next.set("end", defaultEnd);
    }
    const suffix = next.toString();
    return `/business/${nextTopic}${suffix ? `?${suffix}` : ""}`;
  };

  if (datasets.isError) return <main className="p-4 md:p-6"><ErrorState message={(datasets.error as Error).message} retry={() => datasets.refetch()} /></main>;
  if (datasets.isSuccess && !datasets.data?.length) return <main className="p-4 md:p-6"><Card><EmptyState title="尚未导入多业务数据" description="在数据中心导入 AdventureWorks 目录后，广告、退款和物流专题会出现在这里。" /></Card></main>;
  if (datasets.isSuccess && !selectedDataset) return <main className="grid min-h-[calc(100vh-104px)] place-items-center p-6"><EmptyState title="当前数据集没有多业务事实" description="广告、退款和物流分析不会切换到另一份数据。" /></main>;

  return <main className="min-w-0 space-y-4 px-3 py-4 sm:px-4 md:p-6">
    <header className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h1 className="text-xl font-semibold tracking-normal md:text-2xl">多业务专题分析</h1><Badge tone="red"><AlertTriangle size={13} className="mr-1" />演示推算数据</Badge></div><p className="mt-1 text-sm text-muted">{pageConfig.description} · 指标、证据和报告使用同一分析范围</p></div>
      <div className="text-xs text-muted"><span className="block">当前数据集</span><strong className="mt-1 block text-sm font-medium text-ink">{selectedDataset?.name ?? "数据集信息加载中"}</strong></div>
    </header>
    <nav aria-label="多业务专题" className="grid grid-cols-3 overflow-hidden rounded-md border border-line bg-white">{topics.map((item) => <NavLink key={item.id} to={topicHref(item.id)} className={({ isActive }) => cx("flex min-h-[58px] min-w-0 items-center justify-center gap-2 border-r border-line px-2 text-center text-xs font-medium text-muted last:border-r-0 sm:text-sm", isActive && "bg-[#f5f8ff] text-ink")}><item.icon size={17} style={{ color: item.accent }} /><span className="truncate">{item.label}</span></NavLink>)}</nav>
    <section className="flex min-w-0 border-l-4 border-[#f79009] bg-[#fffaeb] px-3 py-3"><div className="flex min-w-0 items-start gap-2"><Database size={16} className="mt-0.5 shrink-0 text-[#b54708]" /><p className="min-w-0 text-xs leading-5 text-[#7a2e0e]"><strong>数据说明：</strong>当前统一数据中的广告、退款和物流来自 AdventureWorks 演示推算事实。结果仅用于演示，不可用于财务核算。</p></div></section>
    {analysis.isLoading ? <PageSkeleton compact /> : analysis.isError ? <ErrorState message={(analysis.error as Error).message} retry={() => analysis.refetch()} /> : analysis.data ? <>
      <FilterBar data={analysis.data} values={filters} update={update} reset={reset} />
      {analysis.data.data_state && analysis.data.data_state !== "READY" && <RangeStateNotice data={analysis.data} reset={reset} useRecommendedPeriod={useRecommendedPeriod} />}
      {!analysis.data.data_state || !["EMPTY", "OUT_OF_RANGE", "INSUFFICIENT_DATA", "FAILED", "FATAL"].includes(analysis.data.data_state) ? <>
        <MetricGrid metrics={analysis.data.metrics} accent={pageConfig.accent} />
        <section className="grid min-w-0 grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,0.85fr)]"><TrendPanel data={analysis.data} accent={pageConfig.accent} /><RankingPanel data={analysis.data} accent={pageConfig.accent} /></section>
        <AnomalyPanel anomalies={analysis.data.anomalies} />
        <section className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2"><CausePanel data={analysis.data} /><ActionPanel data={analysis.data} /></section>
        <EvidencePanel items={analysis.data.evidence} onView={(item) => setDetail({ title: "数据证据", body: <EvidenceBody item={item} /> })} />
        <BusinessDetails topic={topic} data={analysis.data} onView={(row) => setDetail({ title: "明细", body: <DetailBody row={row} /> })} update={update} />
      </> : null}
      <Drawer open={Boolean(detail)} onOpenChange={(open) => { if (!open) setDetail(null); }} title={detail?.title ?? "详情"}>{detail?.body}</Drawer>
    </> : null}
  </main>;
}

function RangeStateNotice({ data, reset, useRecommendedPeriod }: { data: BusinessTopicData; reset: () => void; useRecommendedPeriod: () => void }) {
  const outOfRange = data.data_state === "OUT_OF_RANGE";
  const incomplete = data.data_state === "INCOMPLETE_PERIOD";
  const title = outOfRange ? "当前选择时期没有该专题事实" : incomplete ? "当前范围包含不完整月份" : "当前筛选范围没有该专题事实";
  const available = data.available_periods?.map(item => `${item.start} 至 ${item.end}`).join("；") || "暂无可用时期";
  return <section role="status" className="border-l-4 border-[#f79009] bg-[#fffaeb] px-4 py-4 text-[#7a2e0e]">
    <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0"><h2 className="text-sm font-semibold">{title}</h2><p className="mt-1 break-words text-xs leading-5">选择时期：{data.period.start} 至 {data.period.end}</p><p className="text-xs leading-5">可用时期：{available}</p></div>
      <div className="flex shrink-0 flex-wrap gap-2">{outOfRange && data.recommended_period && <Button onClick={useRecommendedPeriod}>使用可用时期</Button>}{!outOfRange && !incomplete && <Button variant="secondary" onClick={reset}>清除筛选</Button>}</div>
    </div>
  </section>;
}

function EvidencePanel({ items, onView }: { items: BusinessEvidence[]; onView: (item: BusinessEvidence) => void }) {
  return <Card className="p-4"><div className="flex items-center gap-2"><FileSearch size={16} className="text-brand"/><h2 className="text-sm font-semibold">数据证据</h2></div><div className="mt-3 grid gap-2 md:grid-cols-3">{items.slice(0, 6).map(item => <button key={item.evidence_id} onClick={() => onView(item)} className="rounded-md border border-line p-3 text-left hover:bg-[#f8faff]"><p className="text-xs font-medium text-ink">{item.metric}</p><p className="mt-1 text-xs text-muted">{formatValue(item.value)} · 样本 {item.sample_size.toLocaleString()}</p></button>)}</div>{!items.length && <EmptyState title="当前范围没有可展示证据" description="证据将在正式指标与规则产生后出现。"/>}</Card>;
}

function EvidenceBody({ item }: { item: BusinessEvidence }) {
  return <div className="space-y-4"><div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line"><Info label="指标" value={item.metric}/><Info label="证据值" value={formatValue(item.value)}/><Info label="样本量" value={item.sample_size.toLocaleString()}/><Info label="周期" value={`${item.period.start} 至 ${item.period.end}`}/></div><div><p className="text-xs font-semibold">计算公式</p><p className="mt-1 text-sm leading-6 text-muted">{item.formula || "数据不可用"}</p></div><div><p className="text-xs font-semibold">限制</p><p className="mt-1 text-sm leading-6 text-muted">{item.limitations.join("；") || "当前未记录额外限制。"}</p></div></div>;
}

function BusinessDetails({ topic, data, onView, update }: { topic: BusinessTopic; data: BusinessTopicData; onView: (row: Record<string, string | number | null>) => void; update: (key: string, value: string) => void }) {
  const rows = (data.table?.rows ?? data.details) as Array<Record<string, string | number | null>>;
  const fallbackColumns = (rows.length ? detailColumns[topic].filter(column => column in rows[0]) : []).map(field => ({ field, label: detailLabels[field] ?? field, format: "text" }));
  const columns = data.table?.columns ?? fallbackColumns;
  const pagination = data.table?.pagination ?? data.pagination ?? { page: 1, page_size: 20, total: rows.length, pages: 1 };
  return <Card className="overflow-hidden"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-4"><div><h2 className="text-sm font-semibold">明细表</h2><p className="mt-1 text-xs text-muted">共 {pagination.total.toLocaleString()} 条</p></div><div className="flex items-center gap-2"><label className="text-xs text-muted">每页<select value={pagination.page_size} onChange={event => update("page_size", event.target.value)} className="ml-1 h-8 rounded-md border border-line bg-white px-2 text-ink"><option value="20">20</option><option value="50">50</option><option value="100">100</option></select></label><Button variant="ghost" className="h-8 w-8 p-0" disabled={pagination.page <= 1} onClick={() => update("page", String(pagination.page - 1))} aria-label="上一页"><ChevronLeft size={15}/></Button><span className="text-xs text-muted">{pagination.page} / {pagination.pages}</span><Button variant="ghost" className="h-8 w-8 p-0" disabled={pagination.page >= pagination.pages} onClick={() => update("page", String(pagination.page + 1))} aria-label="下一页"><ChevronRight size={15}/></Button></div></div>{rows.length ? <div className="overflow-x-auto"><table className="w-full min-w-[700px] text-left text-xs"><thead className="bg-[#fafbfc] text-muted"><tr>{columns.map(column => <th key={column.field} className="whitespace-nowrap px-3 py-3 font-medium">{column.label}</th>)}<th className="px-3 py-3 text-right font-medium">操作</th></tr></thead><tbody>{rows.map((row, index) => <tr key={index} className="border-t border-line">{columns.map(column => <td key={column.field} className="max-w-[180px] truncate px-3 py-3 text-[#475467]">{String(row[column.field] ?? "-")}</td>)}<td className="px-3 py-2 text-right"><button onClick={() => onView(row)} className="inline-flex h-7 items-center gap-1 rounded px-2 text-xs text-brand hover:bg-[#edf4ff]"><Eye size={13}/>查看</button></td></tr>)}</tbody></table></div> : <EmptyState title="没有明细" description="当前筛选范围内没有记录。"/>}</Card>;
}

function DetailBody({ row }: { row: Record<string, string | number | null> }) { return <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line">{Object.entries(row).map(([key, value]) => <Info key={key} label={detailLabels[key] ?? key} value={String(value ?? "数据不可用")} />)}</div>; }
function Info({ label, value }: { label: string; value: string }) { return <div className="bg-white p-3"><p className="text-xs text-muted">{label}</p><p className="mt-1 text-sm font-medium break-words">{value}</p></div>; }

function FilterBar({ data, values, update, reset }: { data: BusinessTopicData; values: Record<string, string>; update: (key: string, value: string) => void; reset: () => void }) {
  return <Card className="flex min-w-0 flex-wrap items-end gap-2 p-3">
    {(["start", "end"] as const).map((key) => <label key={key} className="min-w-[142px] flex-1 text-[11px] text-muted"><span className="mb-1.5 block">{key === "start" ? "开始日期" : "结束日期"}</span><input aria-label={key === "start" ? "开始日期" : "结束日期"} type="date" value={values[key] ?? ""} onChange={(event) => update(key, event.target.value)} className="h-9 w-full rounded-md border border-line bg-white px-2 text-xs text-ink outline-none focus:border-brand" /></label>)}
    {Object.entries(data.filter_options).map(([key, options]) => <label key={key} className="min-w-[132px] flex-1 text-[11px] text-muted"><span className="mb-1.5 block">{filterLabels[key] ?? key}</span><select value={values[key] ?? ""} onChange={(event) => update(key, event.target.value)} className="h-9 w-full rounded-md border border-line bg-white px-2 text-xs text-ink outline-none focus:border-brand"><option value="">全部</option>{options.map((item) => <option value={item} key={item}>{item}</option>)}</select></label>)}
    <Button variant="secondary" className="h-9 shrink-0" onClick={reset}><RefreshCcw size={14} />重置</Button>
  </Card>;
}

function MetricGrid({ metrics, accent }: { metrics: BusinessMetric[]; accent: string }) {
  return <section aria-label="专题 KPI" className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">{metrics.map((metric) => <Card key={metric.id} className="min-h-[86px] min-w-0 p-3"><div className="mb-2 h-0.5 w-7" style={{ backgroundColor: accent }} /><p className="truncate text-[11px] text-muted">{metric.label}</p><p className="mt-1 truncate text-lg font-semibold tabular-nums sm:text-xl">{formatValue(metric.value, metric.format)}</p></Card>)}</section>;
}

function TrendPanel({ data, accent }: { data: BusinessTopicData; accent: string }) {
  const contract = data.visualizations?.find(item => item.type === "line");
  const rows = contract?.rows ?? data.trend.rows; const series = contract?.series ?? data.trend.series.slice(0, 2).map(field => ({ field, label: field, format: "decimal" })); const dimension = contract?.dimension.field ?? "period";
  const option: EChartsOption = { animationDuration: 300, color: [accent, "#f79009"], tooltip: { trigger: "axis", backgroundColor: "#fff", borderColor: "#e5e9f0", textStyle: { color: "#101828", fontSize: 11 } }, legend: { top: 0, left: 0, itemWidth: 18, itemHeight: 3, textStyle: { fontSize: 10, color: "#667085" } }, grid: { left: 8, right: 12, top: 44, bottom: 8, containLabel: true }, xAxis: { type: "category", boundaryGap: false, data: rows.map((row) => String(row[dimension] ?? "")), axisLabel: { color: "#98a2b3", fontSize: 10 }, axisLine: { lineStyle: { color: "#e5e9f0" } } }, yAxis: { type: "value", scale: true, axisLabel: { color: "#98a2b3", fontSize: 9, formatter: compact }, splitLine: { lineStyle: { color: "#edf0f4", type: "dashed" } } }, series: series.map((item, index) => ({ name: item.label, type: "line", smooth: 0.18, symbolSize: 5, lineStyle: { width: index ? 1.8 : 2.5, type: index ? "dashed" : "solid" }, data: rows.map((row) => chartValue(row[item.field])) })) };
  return <Card className="min-w-0 p-4"><h2 className="text-sm font-semibold">{contract?.title ?? data.trend.title}</h2><p className="mt-1 text-[11px] text-muted">{data.period.start} 至 {data.period.end} · 月度</p>{rows.length ? <EChart option={option} style={{ height: 280, width: "100%" }} notMerge lazyUpdate /> : <EmptyState title="当前范围没有趋势数据" description="调整日期或筛选条件后重试。" />}</Card>;
}

function RankingPanel({ data, accent }: { data: BusinessTopicData; accent: string }) {
  const contract = data.visualizations?.find(item => item.type === "bar");
  const fallback = data.topic === "advertising" ? { name: "campaign_id", value: "spend_usd", format: "currency" } : data.topic === "returns" ? { name: "product_name", value: "refund_amount_usd", format: "currency" } : { name: "carrier_name", value: "delay_rate", format: "percent" };
  const dimension = contract?.dimension.field ?? fallback.name; const series = contract?.series[0] ?? { field: fallback.value, label: fallback.value, format: fallback.format }; const rows = (contract?.rows ?? data.ranking.rows).slice(0, 8); const max = Math.max(...rows.map((row) => Number(row[series.field]) || 0), 1); const valueFormat = (["currency", "integer", "percent", "decimal", "days"] as string[]).includes(series.format) ? series.format as BusinessMetric["format"] : "decimal";
  return <Card className="min-w-0 p-4"><h2 className="text-sm font-semibold">{contract?.title ?? data.ranking.title}</h2><div className="mt-4 space-y-3">{rows.map((row, index) => { const value = Number(row[series.field]) || 0; return <div key={`${String(row[dimension])}-${index}`} className="grid min-w-0 grid-cols-[20px_minmax(0,1fr)_auto] items-center gap-2 text-xs"><span className="text-muted">{index + 1}</span><div className="min-w-0"><span className="block truncate font-medium">{String(row[dimension] ?? "未标注")}</span><div className="mt-1 h-1.5 overflow-hidden bg-[#eef1f5]"><div className="h-full" style={{ width: `${Math.max(3, value / max * 100)}%`, backgroundColor: accent }} /></div></div><strong className="whitespace-nowrap tabular-nums">{formatValue(value, valueFormat)}</strong></div>; })}{!rows.length && <EmptyState title="暂无排名" description="当前筛选范围没有可比较对象。" />}</div></Card>;
}

function AnomalyPanel({ anomalies }: { anomalies: BusinessAnomaly[] }) {
  return <section aria-label="异常列表" className="space-y-2"><div className="flex items-center justify-between"><h2 className="text-sm font-semibold">需要关注的对象</h2><span className="text-xs text-muted">{anomalies.length} 项</span></div>{anomalies.length ? <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">{anomalies.map((item) => <Card key={item.id} className="min-w-0 p-4"><div className="flex min-w-0 items-start justify-between gap-2"><div className="min-w-0"><p className="truncate text-sm font-semibold">{item.title}</p><p className="mt-1 truncate text-xs text-muted">{item.entity}</p></div><Badge tone="red">{item.status}</Badge></div><div className="mt-3 grid grid-cols-2 gap-2 text-xs"><div><p className="text-muted">当前值</p><strong className="mt-1 block tabular-nums">{formatValue(item.current_value)}</strong></div><div><p className="text-muted">较基期</p><strong className="mt-1 block tabular-nums text-danger">{item.change_rate === null ? "不可比" : `${item.change_rate > 0 ? "+" : ""}${(item.change_rate * 100).toFixed(1)}%`}</strong></div></div><p className="mt-3 border-t border-line pt-3 text-[11px] leading-5 text-muted">{item.recommendation || item.reason}</p></Card>)}</div> : <Card><EmptyState title="当前没有需要关注的对象" description="当前筛选范围内没有指标达到处置条件。" /></Card>}</section>;
}

function CausePanel({ data }: { data: BusinessTopicData }) { return <Card className="min-w-0 p-4"><div className="flex items-center gap-2"><Lightbulb size={16} className="text-[#b54708]" /><h2 className="text-sm font-semibold">原因说明</h2></div><div className="mt-3 space-y-3">{data.causes.map((item) => <div key={item.anomaly_id} className="border-l-2 border-[#fdb022] pl-3"><p className="text-xs font-medium">{item.entity}</p><p className="mt-1 text-xs leading-5 text-muted">{item.explanation}</p></div>)}{!data.causes.length && <p className="text-xs leading-5 text-muted">当前没有达到阈值的异常，因此不生成确定性原因判断。</p>}</div></Card>; }
function ActionPanel({ data }: { data: BusinessTopicData }) { return <Card className="min-w-0 p-4"><div className="flex items-center gap-2"><CheckCircle2 size={16} className="text-success" /><h2 className="text-sm font-semibold">行动建议</h2></div><div className="mt-3 space-y-3">{data.actions.map((item) => <div key={item.anomaly_id} className="flex items-start gap-3"><Badge tone={item.priority === "P1" ? "red" : "orange"}>{item.priority}</Badge><div className="min-w-0"><p className="text-xs font-medium leading-5">{item.title}</p></div></div>)}{!data.actions.length && <p className="text-xs leading-5 text-muted">维持监测；证据达到处置条件后再生成行动建议。</p>}</div></Card>; }
function PageSkeleton({ compact = false }: { compact?: boolean }) { return <div className={cx("grid gap-3", !compact && "p-4 md:p-6")}><Skeleton className="h-16 w-full" /><div className="grid grid-cols-2 gap-2 sm:grid-cols-4"><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div><Skeleton className="h-[340px] w-full" /></div>; }
