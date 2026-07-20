import { ChevronLeft, ChevronRight, Download, Search } from "lucide-react";
import { cn } from "../lib/format";
import { Button, Card, EmptyState } from "./ui";

function preferredColumns(rows: Array<Record<string, unknown>>) {
  if (!rows.length) return [];
  const priority = ["name", "market", "product_id", "segment", "primary_category", "gmv", "profit", "profit_rate", "return_rate", "orders", "customers", "classification", "strategy"];
  const keys = Object.keys(rows[0]).filter(key => !key.endsWith("_id") || key === "product_id");
  return [...priority.filter(key => keys.includes(key)), ...keys.filter(key => !priority.includes(key))].slice(0, 7);
}

const labels: Record<string, string> = { name: "对象", market: "市场", product_id: "商品", segment: "客户分群", primary_category: "品类", gmv: "GMV", profit: "利润", profit_rate: "利润率", return_rate: "退货率", orders: "订单数", customers: "客户数", classification: "经营分类", strategy: "策略" };

export function DataGrid({ rows, page, pages, total, onPage, search, onSearch, title = "明细数据" }: { rows: Array<Record<string, unknown>>; page: number; pages: number; total: number; onPage: (page: number) => void; search: string; onSearch: (value: string) => void; title?: string }) {
  const columns = preferredColumns(rows);
  return <Card className="overflow-hidden"><div className="flex min-h-14 items-center justify-between gap-3 border-b border-line px-4"><div><h3 className="text-sm font-semibold">{title}</h3><p className="mt-0.5 text-xs text-muted">共 {total.toLocaleString()} 条记录</p></div><div className="flex items-center gap-2"><label className="flex h-8 items-center gap-2 rounded-md border border-line px-2 text-muted"><Search size={14}/><input className="w-40 bg-transparent text-xs text-ink outline-none" value={search} onChange={event => onSearch(event.target.value)} placeholder="搜索当前明细..."/></label><Button variant="secondary" className="h-8 px-2"><Download size={14}/><span className="hidden sm:inline">导出</span></Button></div></div>{rows.length ? <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left text-xs"><thead className="bg-[#fafbfc] text-muted"><tr>{columns.map(column => <th className="whitespace-nowrap px-4 py-3 font-medium" key={column}>{labels[column] ?? column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr className="border-t border-line hover:bg-[#f8faff]" key={index}>{columns.map(column => <td className="max-w-[220px] truncate px-4 py-3 text-[#344054] tabular-nums" key={column}>{typeof row[column] === "number" ? Number(row[column]).toLocaleString("zh-CN", { maximumFractionDigits: 2 }) : cn(row[column])}</td>)}</tr>)}</tbody></table></div> : <EmptyState title="没有匹配的记录" description="调整搜索词或筛选条件后重试。"/>}<div className="flex h-12 items-center justify-between border-t border-line px-4 text-xs text-muted"><span>第 {page} / {pages} 页</span><div className="flex gap-1"><Button variant="ghost" className="h-8 w-8 p-0" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="上一页"><ChevronLeft size={16}/></Button><Button variant="ghost" className="h-8 w-8 p-0" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="下一页"><ChevronRight size={16}/></Button></div></div></Card>;
}
