import { BarChart3, Bell, Bot, ChevronDown, Database, LayoutDashboard, Menu, Search, UserRound, X } from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useState } from "react";
import { Button, cx, Tooltip } from "./ui";
import { useAppState } from "../state/app";

const navigation = [
  { label: "经营总览", path: "/", icon: LayoutDashboard },
  { label: "专题分析", path: "/analytics", icon: BarChart3 },
  { label: "数据中心", path: "/data", icon: Database },
  { label: "AI分析师", path: "/ai", icon: Bot },
];

function Sidebar({ mobile, close }: { mobile?: boolean; close?: () => void }) {
  return <aside className={cx("flex h-screen w-[212px] shrink-0 flex-col border-r border-line bg-white", mobile && "w-[260px]")}> 
    <div className="flex h-16 items-center justify-between px-5"><img src="/crossborder-logo.png" className="h-8 w-auto object-contain" alt="CrossBorder"/>{mobile && <Button variant="ghost" className="h-8 w-8 p-0" onClick={close}><X size={18}/></Button>}</div>
    <nav className="mt-3 space-y-1 px-3">{navigation.map(item => <NavLink end={item.path === "/"} to={item.path} key={item.path} onClick={close} className={({ isActive }) => cx("flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-[#475467] transition hover:bg-[#f5f7fa]", isActive && "bg-[#edf3ff] text-brand")}><item.icon size={18}/>{item.label}</NavLink>)}</nav>
    <div className="mt-auto p-3"><button className="flex w-full items-center gap-3 rounded-md border border-line px-3 py-3 text-left hover:bg-[#fafbfc]"><Database size={18}/><span className="min-w-0 flex-1 truncate text-sm">跨境电商企业</span><ChevronDown size={15} className="text-muted"/></button><div className="mt-4 flex items-center gap-3 px-2"><div className="grid h-9 w-9 place-items-center rounded-full bg-[#f2f4f7] text-muted"><UserRound size={20}/></div><div><p className="text-sm font-medium">未登录用户</p><p className="text-xs text-muted">本地工作区</p></div></div><p className="mt-8 px-2 text-xs text-[#98a2b3]">版本 3.0.0</p></div>
  </aside>;
}

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const { start, end, setRange } = useAppState();
  const showFilters = location.pathname === "/";
  return <div className="flex min-h-screen bg-canvas text-ink"><div className="hidden lg:block"><Sidebar/></div>{mobileOpen && <div className="fixed inset-0 z-50 flex bg-ink/20 lg:hidden"><Sidebar mobile close={() => setMobileOpen(false)}/><button className="flex-1" aria-label="关闭导航" onClick={() => setMobileOpen(false)}/></div>}<div className="min-w-0 flex-1"><header className="sticky top-0 z-30 flex h-16 items-center gap-4 border-b border-line bg-white/95 px-4 backdrop-blur md:px-6"><Button variant="ghost" className="h-9 w-9 p-0 lg:hidden" onClick={() => setMobileOpen(true)} aria-label="打开导航"><Menu size={19}/></Button>{showFilters ? <><button className="hidden h-9 min-w-[278px] items-center justify-between rounded-md border border-line px-3 text-sm text-[#475467] md:flex"><span className="text-muted">工作空间</span><strong className="font-medium text-ink">默认工作空间</strong><ChevronDown size={15}/></button><label className="hidden items-center gap-2 text-sm text-muted xl:flex">分析周期<select className="h-9 rounded-md border border-line bg-white px-3 text-ink outline-none"><option>月度</option><option>周度</option></select></label><div className="hidden items-center gap-2 xl:flex"><input aria-label="开始日期" type="date" value={start} onChange={event => setRange(event.target.value, end)} className="h-9 rounded-md border border-line px-3 text-sm outline-none focus:border-brand"/><span className="text-muted">至</span><input aria-label="结束日期" type="date" value={end} onChange={event => setRange(start, event.target.value)} className="h-9 rounded-md border border-line px-3 text-sm outline-none focus:border-brand"/></div></> : <button className="hidden h-9 min-w-[278px] items-center justify-between rounded-md border border-line px-3 text-sm text-[#475467] md:flex"><span className="text-muted">工作空间</span><strong className="font-medium text-ink">默认工作空间</strong><ChevronDown size={15}/></button>}<div className="ml-auto flex items-center gap-2"><label className="hidden h-9 w-[310px] items-center gap-2 rounded-md border border-line px-3 text-muted 2xl:flex"><Search size={16}/><input className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none" placeholder="搜索指标、市场、商品、报告..."/><kbd className="text-xs">⌘K</kbd></label><Tooltip label="通知"><Button variant="ghost" className="relative h-9 w-9 p-0" aria-label="通知"><Bell size={19}/><span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-danger"/></Button></Tooltip><div className="grid h-9 w-9 place-items-center rounded-full bg-[#f2f4f7] text-muted"><UserRound size={20}/></div></div></header><main><Outlet/></main></div></div>;
}
