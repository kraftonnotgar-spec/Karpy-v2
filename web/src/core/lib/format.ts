/** Money as the API sends it: integer minor units as a string plus an ISO 4217 code. */
export type Money = { amount_minor: string; currency: string };

export function formatMoneyParts(money: Money, locale?: string, options?: { trimWhole?: boolean }) {
  const formatter = new Intl.NumberFormat(locale, {
    style: "currency",
    currency: money.currency,
    currencyDisplay: "code",
  });
  const digits = formatter.resolvedOptions().maximumFractionDigits ?? 2;
  const minor = BigInt(money.amount_minor);
  const negative = minor < BigInt(0);
  const absolute = negative ? -minor : minor;
  const scale = BigInt(10) ** BigInt(digits);
  // Intl supports exact decimal strings. Never round int64 money through a float.
  const decimal = `${negative ? "-" : ""}${absolute / scale}.${(absolute % scale).toString().padStart(digits || 1, "0")}`;
  const displayFormatter = options?.trimWhole !== false && absolute % scale === BigInt(0)
    ? new Intl.NumberFormat(locale, { ...formatter.resolvedOptions(), minimumFractionDigits: 0 })
    : formatter;
  return displayFormatter.formatToParts(decimal as unknown as number);
}
export function formatMoney(money: Money, locale?: string, options?: { trimWhole?: boolean }) {
  return formatMoneyParts(money, locale, options).map((part) => part.value).join("");
}
export function formatNumber(value: number, locale?: string, options?: Intl.NumberFormatOptions) {
  return new Intl.NumberFormat(locale, options).format(value);
}
export function formatCompact(value: number, locale?: string) {
  return new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}
export function formatPercent(value: number, locale?: string) {
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 2 }).format(value / 100);
}
export function formatDate(value: string, locale?: string, timeZone?: string) {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
    hourCycle: "h23",
  }).format(new Date(value));
}
/** Short day label for chart axes ("12 Mar"). Accepts YYYY-MM-DD or ISO timestamps. */
export function formatDay(value: string, locale?: string) {
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00Z`) : new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", timeZone: "UTC" }).format(date);
}
/** Percentage change from previous to current; null when there is nothing to compare. */
export function percentChange(current: number, previous: number | null | undefined) {
  if (previous === null || previous === undefined || previous === 0) return null;
  return ((current - previous) / Math.abs(previous)) * 100;
}
