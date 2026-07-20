import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { X } from "lucide-react";
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { twMerge } from "tailwind-merge";

export function cx(...values: Array<string | false | null | undefined>) { return twMerge(values.filter(Boolean).join(" ")); }

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <section className={cx("rounded-panel border border-line bg-white shadow-panel", className)} {...props} />;
}

export function Button({ className, variant = "default", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "secondary" | "ghost" | "danger" }) {
  const variants = {
    default: "bg-brand text-white hover:bg-[#075ce8]",
    secondary: "border border-line bg-white text-ink hover:bg-[#f8fafc]",
    ghost: "text-muted hover:bg-[#f1f5f9] hover:text-ink",
    danger: "bg-danger text-white hover:bg-[#d92d20]",
  };
  return <button className={cx("inline-flex h-9 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30 disabled:cursor-not-allowed disabled:opacity-50", variants[variant], className)} {...props} />;
}

export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: "neutral" | "blue" | "green" | "orange" | "red"; className?: string }) {
  const tones = { neutral: "bg-[#f2f4f7] text-[#475467]", blue: "bg-[#eff4ff] text-brand", green: "bg-[#ecfdf3] text-[#027a48]", orange: "bg-[#fffaeb] text-[#b54708]", red: "bg-[#fef3f2] text-[#b42318]" };
  return <span className={cx("inline-flex h-6 items-center rounded px-2 text-xs font-medium", tones[tone], className)}>{children}</span>;
}

export function Skeleton({ className }: { className?: string }) { return <div className={cx("animate-pulse rounded-md bg-[#eef2f6]", className)} />; }

export function EmptyState({ title, description }: { title: string; description: string }) {
  return <div className="flex min-h-48 flex-col items-center justify-center px-6 text-center"><p className="font-medium text-ink">{title}</p><p className="mt-2 max-w-sm text-sm text-muted">{description}</p></div>;
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="rounded-panel border border-danger/20 bg-[#fff7f6] p-5"><p className="font-medium text-danger">暂时无法加载</p><p className="mt-1 text-sm text-muted">{message}</p>{retry && <Button className="mt-4" variant="secondary" onClick={retry}>重新加载</Button>}</div>;
}

export function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  return <TooltipPrimitive.Provider delayDuration={250}><TooltipPrimitive.Root><TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger><TooltipPrimitive.Portal><TooltipPrimitive.Content sideOffset={6} className="z-50 rounded bg-ink px-2 py-1 text-xs text-white shadow-lg">{label}</TooltipPrimitive.Content></TooltipPrimitive.Portal></TooltipPrimitive.Root></TooltipPrimitive.Provider>;
}

export function Drawer({ open, onOpenChange, title, children }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; children: ReactNode }) {
  return <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}><DialogPrimitive.Portal><DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/20" /><DialogPrimitive.Content className="fixed inset-y-0 right-0 z-50 w-full max-w-[440px] overflow-y-auto border-l border-line bg-white p-6 shadow-2xl"><div className="flex items-center justify-between"><DialogPrimitive.Title className="text-lg font-semibold">{title}</DialogPrimitive.Title><DialogPrimitive.Close asChild><Button variant="ghost" className="h-8 w-8 p-0" aria-label="关闭"><X size={18}/></Button></DialogPrimitive.Close></div><div className="mt-6">{children}</div></DialogPrimitive.Content></DialogPrimitive.Portal></DialogPrimitive.Root>;
}
