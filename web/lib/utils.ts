import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** "今天" / "3 天前" for an ISO timestamp. */
export function daysAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const days = Math.floor((now - Date.parse(iso)) / DAY_MS);
  if (Number.isNaN(days)) return "";
  if (days <= 0) return "今天";
  return `${days} 天前`;
}

export function formatSalary(salary: {
  min: number | null;
  max: number | null;
  currency: string | null;
  period: string;
}): string {
  const fmt = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`);
  const range =
    salary.min != null && salary.max != null && salary.min !== salary.max
      ? `${fmt(salary.min)}–${fmt(salary.max)}`
      : fmt((salary.min ?? salary.max) as number);
  const per = { year: "/年", month: "/月", hour: "/時" }[salary.period] ?? "";
  return `${salary.currency ?? ""} ${range}${per}`.trim();
}
