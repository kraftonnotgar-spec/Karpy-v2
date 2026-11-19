/** Inclusive calendar date range as YYYY-MM-DD strings (UTC), as admin widget endpoints expect. */
export type DateRange = { from: string; to: string };

export const DATE_RANGE_PRESETS = [7, 30, 90] as const;
export type DateRangePreset = (typeof DATE_RANGE_PRESETS)[number];
export const DEFAULT_DATE_RANGE_PRESET: DateRangePreset = 30;

const iso = (date: Date) => date.toISOString().slice(0, 10);

/** The last `days` days, ending today (UTC). */
export function presetRange(days: number, now = new Date()): DateRange {
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const start = new Date(end);
  start.setUTCDate(end.getUTCDate() - (days - 1));
  return { from: iso(start), to: iso(end) };
}

export function withRange(endpoint: string, range: DateRange) {
  const separator = endpoint.includes("?") ? "&" : "?";
  return `${endpoint}${separator}${new URLSearchParams({ from: range.from, to: range.to })}`;
}
