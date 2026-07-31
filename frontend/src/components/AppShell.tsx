import { useQuery } from "@tanstack/react-query";
import { BarChart3, Bell, Bot, ChevronDown, Database, LayoutDashboard, Menu, PanelsTopLeft, Search, UserRound, X } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api, queryString } from "../lib/api";
import { useAppState } from "../state/app";
import type { DatasetCapability, DatasetSummary, FactCapability } from "../types";
import { Badge, Button, cx, Tooltip } from "./ui";

const navigation = [
  { label: "经营总览", path: "/", icon: LayoutDashboard },
  { label: "专题分析", path: "/analytics", icon: BarChart3 },
  { label: "多业务分析", path: "/business", icon: PanelsTopLeft },
  { label: "数据中心", path: "/data", icon: Database },
  { label: "AI分析师", path: "/ai", icon: Bot },
];

function factForPath(pathname: string): FactCapability["fact"] {
  if (pathname.startsWith("/business/returns")) return "refunds";
  if (pathname.startsWith("/business/logistics")) return "logistics";
  if (pathname.startsWith("/business")) return "advertising";
  return "orders";
}

function Sidebar({ mobile, close }: { mobile?: boolean; close?: () => void }) {
  return <aside className={cx("flex h-screen w-[212px] shrink-0 flex-col border-r border-line bg-white", mobile && "w-[260px]")}>
    <div className="flex h-16 items-center justify-between px-5"><img src="/crossborder-logo.png" className="h-8 w-auto object-contain" alt="CrossBorder"/>{mobile && <Button variant="ghost" className="h-8 w-8 p-0" onClick={close}><X size={18}/></Button>}</div>
    <nav className="mt-3 space-y-1 px-3">{navigation.map(item => <NavLink end={item.path === "/"} to={item.path} key={item.path} onClick={close} className={({ isActive }) => cx("flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-[#475467] transition hover:bg-[#f5f7fa]", isActive && "bg-[#edf3ff] text-brand")}><item.icon size={18}/>{item.label}</NavLink>)}</nav>
    <div className="mt-auto p-3"><div className="flex w-full items-center gap-3 rounded-md border border-line px-3 py-3 text-left"><Database size={18}/><span className="min-w-0 flex-1 truncate text-sm">本地工作区</span></div><div className="mt-4 flex items-center gap-3 px-2"><div className="grid h-9 w-9 place-items-center rounded-full bg-[#f2f4f7] text-muted"><UserRound size={20}/></div><div><p className="text-sm font-medium">未登录用户</p><p className="text-xs text-muted">本地工作区</p></div></div><p className="mt-8 px-2 text-xs text-[#98a2b3]">版本 4.0.0</p></div>
  </aside>;
}

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const { datasetId, setDatasetId, start, end, rangeSource, rangeFact, setRange, setAutomaticRange } = useAppState();
  const activeFact = factForPath(location.pathname);
  const datasets = useQuery({
    queryKey: ["datasets"],
    queryFn: () => api<DatasetSummary[]>("/datasets"),
    staleTime: 5 * 60_000,
    refetchOnMount: false,
  });
  const items = datasets.data?.data ?? [];
  const selected = items.find(item => item.dataset_id === datasetId);
  const hasUserRange = rangeSource === "USER" && Boolean(start && end);
  const capabilities = useQuery({
    queryKey: ["dataset-capabilities", datasetId, activeFact, hasUserRange ? start : "", hasUserRange ? end : ""],
    queryFn: () => api<DatasetCapability>(`/datasets/${datasetId}/capabilities${queryString({ fact: activeFact, start: hasUserRange ? start : undefined, end: hasUserRange ? end : undefined })}`).then(result => result.data),
    enabled: Boolean(datasetId),
    staleTime: 5 * 60_000,
  });
  const activeCapability = capabilities.data?.facts[activeFact];
  const showFilters = location.pathname === "/";
  const analysisBlocked = !datasetId && location.pathname !== "/data";
  const managesRange = location.pathname !== "/data";
  const needsAutomaticRange = rangeSource === "AUTO" && (rangeFact !== activeFact || !start || !end);
  const rangePending = Boolean(datasetId && managesRange && needsAutomaticRange && !capabilities.isError && !(capabilities.isSuccess && !activeCapability?.recommended_period));

  useEffect(() => {
    if (!datasets.isSuccess) return;
    if (!datasetId && items.length) {
      setDatasetId(items[0].dataset_id);
      return;
    }
    if (items.length === 1 && datasetId !== items[0].dataset_id) {
      setDatasetId(items[0].dataset_id);
      return;
    }
    if (datasetId && !selected) setDatasetId("");
  }, [datasetId, datasets.isSuccess, items, selected, setDatasetId]);

  useEffect(() => {
    const recommended = activeCapability?.recommended_period;
    if (rangeSource === "AUTO" && recommended && (rangeFact !== activeFact || start !== recommended.start || end !== recommended.end)) {
      setAutomaticRange(recommended.start, recommended.end, activeFact);
    }
  }, [activeCapability, activeFact, end, rangeFact, rangeSource, setAutomaticRange, start]);

  return <div className="flex min-h-screen bg-canvas text-ink">
    <div className="hidden lg:block"><Sidebar/></div>
    {mobileOpen && <div className="fixed inset-0 z-50 flex bg-ink/20 lg:hidden"><Sidebar mobile close={() => setMobileOpen(false)}/><button className="flex-1" aria-label="关闭导航" onClick={() => setMobileOpen(false)}/></div>}
    <div className="min-w-0 flex-1">
      <header className="sticky top-0 z-30 border-b border-line bg-white/95 backdrop-blur">
        <div className="flex h-16 items-center gap-3 px-4 md:px-6">
          <Button variant="ghost" className="h-9 w-9 shrink-0 p-0 lg:hidden" onClick={() => setMobileOpen(true)} aria-label="打开导航"><Menu size={19}/></Button>
          <label className="min-w-0 flex-1 md:max-w-[360px]"><span className="sr-only">当前数据集</span><select aria-label="当前数据集" value={datasetId} onChange={event => setDatasetId(event.target.value)} className="h-9 w-full rounded-md border border-line bg-white px-3 text-sm text-ink outline-none focus:border-brand"><option value="">选择数据集</option>{items.map(item => <option key={item.dataset_id} value={item.dataset_id}>{item.name}</option>)}</select></label>
          {showFilters && <div className="hidden items-center gap-2 xl:flex"><input aria-label="开始日期" type="date" value={start} onChange={event => setRange(event.target.value, end)} className="h-9 rounded-md border border-line px-3 text-sm outline-none focus:border-brand"/><span className="text-muted">至</span><input aria-label="结束日期" type="date" value={end} onChange={event => setRange(start, event.target.value)} className="h-9 rounded-md border border-line px-3 text-sm outline-none focus:border-brand"/></div>}
          <div className="ml-auto hidden items-center gap-2 md:flex"><label className="hidden h-9 w-[280px] items-center gap-2 rounded-md border border-line px-3 text-muted 2xl:flex"><Search size={16}/><input className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none" placeholder="搜索指标、市场、商品、报告..."/></label><Tooltip label="通知"><Button variant="ghost" className="relative h-9 w-9 p-0" aria-label="通知"><Bell size={19}/><span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-danger"/></Button></Tooltip><div className="grid h-9 w-9 place-items-center rounded-full bg-[#f2f4f7] text-muted"><UserRound size={20}/></div></div>
        </div>
        {selected && <div className="flex min-h-9 flex-wrap items-center gap-x-3 gap-y-1 border-t border-line px-4 py-1.5 text-xs text-muted md:px-6"><strong className="font-medium text-ink">{selected.name}</strong><span>来源：{selected.source_type}</span><span>{start && end ? `${start} 至 ${end}` : "时期读取中"}</span><Badge tone={rangeSource === "AUTO" ? "blue" : "neutral"}>{rangeSource === "AUTO" ? "系统推荐" : "手动范围"}</Badge>{activeCapability && <Badge tone={activeCapability.state === "READY" ? "green" : activeCapability.state === "INCOMPLETE_PERIOD" ? "orange" : "red"}>{activeCapability.state}</Badge>}<span>{selected.row_count.toLocaleString()} 行</span><span>质量 {selected.quality_score.toFixed(0)}</span><span>更新 {new Date(selected.updated_at).toLocaleString("zh-CN", { hour12: false })}</span><Badge tone={selected.is_demo ? "blue" : "green"}>{selected.is_demo ? "示例数据" : "私有数据"}</Badge><details className="group"><summary className="flex cursor-pointer list-none items-center gap-1 font-medium text-brand">数据说明<ChevronDown size={13} className="transition group-open:rotate-180"/></summary><div className="mt-2 space-y-1 border-l-2 border-line pl-2 text-[11px] leading-5"><p className="break-all">内部数据标识：{selected.dataset_id}</p><p>完整来源：{selected.source_type}</p></div></details></div>}
      </header>
      <main>{analysisBlocked ? <section className="grid min-h-[calc(100vh-64px)] place-items-center p-6 text-center"><div><Database size={28} className="mx-auto text-muted"/><h1 className="mt-3 text-lg font-semibold">未选择数据集</h1><p className="mt-1 text-sm text-muted">当前没有可用于分析的数据范围。</p><div className="mt-5 flex flex-wrap justify-center gap-2"><Button disabled={!items.length} onClick={() => items[0] && setDatasetId(items[0].dataset_id)}>使用统一演示数据</Button><NavLink to="/data" className="inline-flex h-9 items-center justify-center rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-[#f8fafc]">导入我的数据</NavLink></div></div></section> : rangePending ? <section aria-label="正在读取可用时期" className="space-y-4 p-4 md:p-6"><div className="h-7 w-52 animate-pulse rounded bg-[#e9edf3]"/><div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map(item => <div key={item} className="h-24 animate-pulse rounded-md border border-line bg-white"/>)}</div><div className="h-[320px] animate-pulse rounded-md border border-line bg-white"/></section> : <Outlet/>}</main>
    </div>
  </div>;
}
