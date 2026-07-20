export function formatValue(value: unknown, format = "integer") {
  const numeric = typeof value === "number" ? value : Number(value ?? 0);
  if (format === "currency") return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 }).format(numeric);
  if (format === "percent") return `${(numeric * 100).toFixed(1)}%`;
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(numeric);
}

export function formatChange(value?: number | null) {
  if (value === undefined || value === null) return "暂无对比";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(1)}%`;
}

export function cn(value: unknown) {
  return value == null || value === "" ? "不可用" : String(value);
}
