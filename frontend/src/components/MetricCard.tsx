import { CircleDollarSign, Percent, ReceiptText, ShoppingCart, TrendingDown, TrendingUp } from "lucide-react";
import type { Kpi } from "../types";
import { formatChange, formatValue } from "../lib/format";
import { Card, cx } from "./ui";

const tones = {
  blue: "bg-[#edf4ff] text-brand",
  violet: "bg-[#f4ebff] text-[#7f56d9]",
  green: "bg-[#eafbf3] text-success",
  orange: "bg-[#fff4e8] text-warning",
};

export function MetricCard({ metric, compact = false }: { metric: Kpi; compact?: boolean }) {
  const tone = metric.tone ?? "blue";
  const Icon = tone === "violet" ? Percent : tone === "green" ? ShoppingCart : tone === "orange" ? CircleDollarSign : ReceiptText;
  const positive = (metric.change ?? 0) >= 0;
  return <Card className={cx("flex min-h-[104px] items-center", compact ? "gap-3 p-3" : "gap-4 p-4")}>
    <div className={cx("grid shrink-0 place-items-center rounded-lg", compact ? "h-10 w-10" : "h-11 w-11", tones[tone])}><Icon size={compact ? 20 : 22}/></div>
    <div className="min-w-0 flex-1"><p className="text-sm text-muted">{metric.label}</p><p className="mt-1 whitespace-nowrap text-[22px] font-semibold tabular-nums text-ink">{formatValue(metric.value, metric.format)}</p><div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs"><span className={cx("inline-flex items-center gap-1 font-medium", positive ? "text-success" : "text-danger")}>{positive ? <TrendingUp size={13}/> : <TrendingDown size={13}/>} {formatChange(metric.change)}</span><span className="text-muted">较上期</span></div></div>
  </Card>;
}
