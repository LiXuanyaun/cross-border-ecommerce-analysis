import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Database, Lightbulb, Megaphone, RefreshCcw, Truck, Undo2 } from "lucide-react";
import { useEffect, useMemo } from "react";
import { NavLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton, cx } from "../../components/ui";
import { EChart, type EChartsOption } from "../../components/EChart";
import { api, queryString } from "../../lib/api";
import type { BusinessAnomaly, BusinessDataset, BusinessMetric, BusinessTopic, BusinessTopicData } from "../../types";

const topics = [
  { id: "advertising", label: "广告分析", icon: Megaphone, accent: "#1769ff", description: "投放效率与归因收入" },
  { id: "returns", label: "退款分析", icon: Undo2, accent: "#e5484d", description: "退货原因与退款风险" },
  { id: "logistics", label: "物流分析", icon: Truck, accent: "#0e9384", description: "运输时效与轨迹异常" },
] as const;
const validTopics = new Set<BusinessTopic>(topics.map((item) => item.id));
const filterLabels: Record<string, string> = { country: "国家", channel: "渠道", platform: "平台", campaign_id: "活动", category: "品类", return_reason: "退货原因", carrier_id: "承运商", region: "地区" };

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

export function BusinessAnalysisPage() {
  const route = useParams();
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const rawTopic = route.topic as BusinessTopic | undefined;
  const topic = rawTopic && validTopics.has(rawTopic) ? rawTopic : "advertising";
  const pageConfig = config(topic);
  useEffect(() => { if (!rawTopic || !validTopics.has(rawTopic)) navigate("/business/advertising", { replace: true }); }, [navigate, rawTopic]);

  const datasets = useQuery({ queryKey: ["business-datasets"], queryFn: () => api<BusinessDataset[]>("/business/datasets").then((result) => result.data) });
  const datasetId = search.get("dataset_id") ?? datasets.data?.[0]?.dataset_id ?? "";
  const filters = useMemo(() => {
    const values: Record<string, string> = {};
    ["start", "end", "country", "channel", "platform", "campaign_id", "category", "return_reason", "carrier_id", "region"].forEach((key) => { const value = search.get(key); if (value) values[key] = value; });
    return values;
  }, [search]);
  const analysis = useQuery({
    queryKey: ["business-topic", topic, datasetId, filters],
    queryFn: () => api<BusinessTopicData>(`/business/${topic}${queryString({ dataset_id: datasetId, ...filters })}`).then((result) => result.data),
    enabled: Boolean(datasetId),
  });
  const update = (key: string, value: string) => { const next = new URLSearchParams(search); if (value) next.set(key, value); else next.delete(key); setSearch(next); };
  const reset = () => { const next = new URLSearchParams(); if (datasetId) next.set("dataset_id", datasetId); setSearch(next); };

  if (datasets.isLoading) return <PageSkeleton />;
  if (datasets.isError) return <main className="p-4 md:p-6"><ErrorState message={(datasets.error as Error).message} retry={() => datasets.refetch()} /></main>;
  if (!datasets.data?.length) return <main className="p-4 md:p-6"><Card><EmptyState title="尚未导入多业务数据" description="在数据中心导入 AdventureWorks 目录后，广告、退款和物流专题会出现在这里。" /></Card></main>;

  return <main className="min-w-0 space-y-4 px-3 py-4 sm:px-4 md:p-6">
    <header className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h1 className="text-xl font-semibold tracking-normal md:text-2xl">多业务专题分析</h1><Badge tone="red"><AlertTriangle size={13} className="mr-1" />模拟数据</Badge></div><p className="mt-1 text-sm text-muted">{pageConfig.description} · 指标、规则、证据和报告使用同一分析范围</p></div>
      <label className="w-full text-xs text-muted xl:w-[310px]"><span className="mb-1.5 block">分析数据集</span><select value={datasetId} onChange={(event) => update("dataset_id", event.target.value)} className="h-9 w-full rounded-md border border-line bg-white px-3 text-sm text-ink outline-none focus:border-brand">{datasets.data.map((item) => <option key={item.dataset_id} value={item.dataset_id}>{item.name}</option>)}</select></label>
    </header>
    <nav aria-label="多业务专题" className="grid grid-cols-3 overflow-hidden rounded-md border border-line bg-white">{topics.map((item) => <NavLink key={item.id} to={`/business/${item.id}${search.toString() ? `?${search}` : ""}`} className={({ isActive }) => cx("flex min-h-[58px] min-w-0 items-center justify-center gap-2 border-r border-line px-2 text-center text-xs font-medium text-muted last:border-r-0 sm:text-sm", isActive && "bg-[#f5f8ff] text-ink")}><item.icon size={17} style={{ color: item.accent }} /><span className="truncate">{item.label}</span></NavLink>)}</nav>
    <section className="flex min-w-0 flex-col gap-2 border-l-4 border-[#f79009] bg-[#fffaeb] px-3 py-3 sm:flex-row sm:items-center sm:justify-between"><div className="flex min-w-0 items-start gap-2"><Database size={16} className="mt-0.5 shrink-0 text-[#b54708]" /><p className="min-w-0 text-xs leading-5 text-[#7a2e0e]"><strong>来源标识：</strong>AdventureWorks 原始订单 + synthetic_extension 广告、退款、物流数据。以下结果不代表真实经营表现。</p></div>{analysis.data && <span className="shrink-0 text-[11px] text-[#93370d]">scope {analysis.data.scope_id.replace("scope_", "")}</span>}</section>
    {analysis.isLoading ? <PageSkeleton compact /> : analysis.isError ? <ErrorState message={(analysis.error as Error).message} retry={() => analysis.refetch()} /> : analysis.data ? <>
      <FilterBar data={analysis.data} values={filters} update={update} reset={reset} />
      <MetricGrid metrics={analysis.data.metrics} accent={pageConfig.accent} />
      <section className="grid min-w-0 grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,0.85fr)]"><TrendPanel data={analysis.data} accent={pageConfig.accent} /><RankingPanel data={analysis.data} topic={topic} accent={pageConfig.accent} /></section>
      <AnomalyPanel anomalies={analysis.data.anomalies} />
      <section className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2"><CausePanel data={analysis.data} /><ActionPanel data={analysis.data} /></section>
    </> : null}
  </main>;
}

function FilterBar({ data, values, update, reset }: { data: BusinessTopicData; values: Record<string, string>; update: (key: string, value: string) => void; reset: () => void }) {
  return <Card className="flex min-w-0 flex-wrap items-end gap-2 p-3">
    {(["start", "end"] as const).map((key) => <label key={key} className="min-w-[142px] flex-1 text-[11px] text-muted"><span className="mb-1.5 block">{key === "start" ? "开始日期" : "结束日期"}</span><input aria-label={key === "start" ? "开始日期" : "结束日期"} type="date" value={values[key] ?? ""} onChange={(event) => update(key, event.target.value)} className="h-9 w-full rounded-md border border-line bg-white px-2 text-xs text-ink outline-none focus:border-brand" /></label>)}
    {Object.entries(data.filter_options).map(([key, options]) => <label key={key} className="min-w-[132px] flex-1 text-[11px] text-muted"><span className="mb-1.5 block">{filterLabels[key] ?? key}</span><select value={values[key] ?? ""} onChange={(event) => update(key, event.target.value)} className="h-9 w-full rounded-md border border-line bg-white px-2 text-xs text-ink outline-none focus:border-brand"><option value="">全部</option>{options.map((item) => <option value={item} key={item}>{item}</option>)}</select></label>)}
    <Button variant="secondary" className="h-9 shrink-0" onClick={reset}><RefreshCcw size={14} />重置</Button>
  </Card>;
}

function MetricGrid({ metrics, accent }: { metrics: BusinessMetric[]; accent: string }) {
  return <section aria-label="专题 KPI" className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">{metrics.map((metric) => <Card key={metric.id} className="min-w-0 p-3"><div className="mb-2 h-0.5 w-7" style={{ backgroundColor: accent }} /><p className="truncate text-[11px] text-muted">{metric.label}</p><p className="mt-1 truncate text-lg font-semibold tabular-nums sm:text-xl">{formatValue(metric.value, metric.format)}</p><p className="mt-1 line-clamp-2 min-h-8 text-[10px] leading-4 text-[#98a2b3]">{metric.formula}</p></Card>)}</section>;
}

function TrendPanel({ data, accent }: { data: BusinessTopicData; accent: string }) {
  const rows = data.trend.rows; const series = data.trend.series.slice(0, 2);
  const option: EChartsOption = { animationDuration: 300, color: [accent, "#f79009"], tooltip: { trigger: "axis", backgroundColor: "#fff", borderColor: "#e5e9f0", textStyle: { color: "#101828", fontSize: 11 } }, legend: { top: 0, left: 0, itemWidth: 18, itemHeight: 3, textStyle: { fontSize: 10, color: "#667085" } }, grid: { left: 8, right: 12, top: 44, bottom: 8, containLabel: true }, xAxis: { type: "category", boundaryGap: false, data: rows.map((row) => String(row.period ?? "")), axisLabel: { color: "#98a2b3", fontSize: 10 }, axisLine: { lineStyle: { color: "#e5e9f0" } } }, yAxis: { type: "value", scale: true, axisLabel: { color: "#98a2b3", fontSize: 9, formatter: compact }, splitLine: { lineStyle: { color: "#edf0f4", type: "dashed" } } }, series: series.map((key, index) => ({ name: key, type: "line", smooth: 0.18, symbolSize: 5, lineStyle: { width: index ? 1.8 : 2.5, type: index ? "dashed" : "solid" }, data: rows.map((row) => row[key]) })) };
  return <Card className="min-w-0 p-4"><h2 className="text-sm font-semibold">{data.trend.title}</h2><p className="mt-1 text-[11px] text-muted">{data.period.start} 至 {data.period.end} · 月度</p>{rows.length ? <EChart option={option} style={{ height: 280, width: "100%" }} notMerge lazyUpdate /> : <EmptyState title="当前范围没有趋势数据" description="调整日期或筛选条件后重试。" />}</Card>;
}

function RankingPanel({ data, topic, accent }: { data: BusinessTopicData; topic: BusinessTopic; accent: string }) {
  const rows = data.ranking.rows.slice(0, 8); const rank = topic === "advertising" ? { name: "campaign_id", value: "spend_usd", format: "currency" as const } : topic === "returns" ? { name: "product_name", value: "refund_amount_usd", format: "currency" as const } : { name: "carrier_name", value: "delay_rate", format: "percent" as const }; const max = Math.max(...rows.map((row) => Number(row[rank.value]) || 0), 1);
  return <Card className="min-w-0 p-4"><h2 className="text-sm font-semibold">{data.ranking.title}</h2><div className="mt-4 space-y-3">{rows.map((row, index) => { const value = Number(row[rank.value]) || 0; return <div key={`${String(row[rank.name])}-${index}`} className="grid min-w-0 grid-cols-[20px_minmax(0,1fr)_auto] items-center gap-2 text-xs"><span className="text-muted">{index + 1}</span><div className="min-w-0"><span className="block truncate font-medium">{String(row[rank.name] ?? "未标注")}</span><div className="mt-1 h-1.5 overflow-hidden bg-[#eef1f5]"><div className="h-full" style={{ width: `${Math.max(3, value / max * 100)}%`, backgroundColor: accent }} /></div></div><strong className="whitespace-nowrap tabular-nums">{formatValue(value, rank.format)}</strong></div>; })}{!rows.length && <EmptyState title="暂无排名" description="当前筛选范围没有可比较对象。" />}</div></Card>;
}

function AnomalyPanel({ anomalies }: { anomalies: BusinessAnomaly[] }) {
  return <section aria-label="异常列表" className="space-y-2"><div className="flex items-center justify-between"><h2 className="text-sm font-semibold">异常列表</h2><span className="text-xs text-muted">{anomalies.length} 项规则命中</span></div>{anomalies.length ? <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">{anomalies.map((item) => <Card key={item.id} className="min-w-0 p-4"><div className="flex min-w-0 items-start justify-between gap-2"><div className="min-w-0"><p className="truncate text-sm font-semibold">{item.title}</p><p className="mt-1 truncate text-xs text-muted">{item.entity}</p></div><Badge tone="red">{item.status}</Badge></div><div className="mt-3 grid grid-cols-2 gap-2 text-xs"><div><p className="text-muted">当前值</p><strong className="mt-1 block tabular-nums">{formatValue(item.current_value)}</strong></div><div><p className="text-muted">较基期</p><strong className="mt-1 block tabular-nums text-danger">{item.change_rate === null ? "不可比" : `${item.change_rate > 0 ? "+" : ""}${(item.change_rate * 100).toFixed(1)}%`}</strong></div></div><p className="mt-3 border-t border-line pt-3 text-[11px] leading-5 text-muted">规则 {item.rule_id} v{item.rule_version} · {item.threshold}</p></Card>)}</div> : <Card><EmptyState title="未命中异常规则" description="当前筛选范围内没有指标达到版本化阈值。" /></Card>}</section>;
}

function CausePanel({ data }: { data: BusinessTopicData }) { return <Card className="min-w-0 p-4"><div className="flex items-center gap-2"><Lightbulb size={16} className="text-[#b54708]" /><h2 className="text-sm font-semibold">原因说明</h2></div><div className="mt-3 space-y-3">{data.causes.map((item) => <div key={item.anomaly_id} className="border-l-2 border-[#fdb022] pl-3"><p className="text-xs font-medium">{item.entity}</p><p className="mt-1 text-xs leading-5 text-muted">{item.explanation}</p></div>)}{!data.causes.length && <p className="text-xs leading-5 text-muted">当前没有达到阈值的异常，因此不生成确定性原因判断。</p>}</div></Card>; }
function ActionPanel({ data }: { data: BusinessTopicData }) { return <Card className="min-w-0 p-4"><div className="flex items-center gap-2"><CheckCircle2 size={16} className="text-success" /><h2 className="text-sm font-semibold">行动建议</h2></div><div className="mt-3 space-y-3">{data.actions.map((item) => <div key={item.anomaly_id} className="flex items-start gap-3"><Badge tone={item.priority === "P1" ? "red" : "orange"}>{item.priority}</Badge><div className="min-w-0"><p className="text-xs font-medium leading-5">{item.title}</p><p className="mt-1 text-[11px] text-muted">复核阈值：{item.threshold}</p></div></div>)}{!data.actions.length && <p className="text-xs leading-5 text-muted">维持监测；证据达到规则阈值后再生成处置建议。</p>}</div></Card>; }
function PageSkeleton({ compact = false }: { compact?: boolean }) { return <div className={cx("grid gap-3", !compact && "p-4 md:p-6")}><Skeleton className="h-16 w-full" /><div className="grid grid-cols-2 gap-2 sm:grid-cols-4"><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div><Skeleton className="h-[340px] w-full" /></div>; }
