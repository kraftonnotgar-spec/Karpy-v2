"use client";

import { useEffect, useMemo, useState } from "react";
import { useT } from "@/core/i18n/provider";
import { cn } from "@/lib/utils";
import { fetchBadgeCount } from "./console-api";
import type { BadgeTone, ConsoleMenuItem, ConsoleSection } from "./console-types";

/** How often menu badge counts refresh while the console is open. */
export const BADGE_REFRESH_MS = 60_000;
const MAX_SHOWN = 999;

/** Tone → design tokens (never colours). */
const toneClass: Record<BadgeTone, string> = {
  default: "bg-primary/10 text-primary",
  attention: "bg-warning-surface text-warning",
  danger: "bg-failure-surface text-failure",
};
const toneRank: Record<BadgeTone, number> = { default: 0, attention: 1, danger: 2 };

export function MenuCountBadge({ count, tone }: { count: number | undefined; tone: BadgeTone }) {
  const t = useT();
  if (!count) return null;
  const label = t("admin.badgeCount", { count: count.toLocaleString(t.locale) });
  return (
    <span
      data-badge-tone={tone}
      aria-label={label}
      title={label}
      className={cn("ml-auto inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-md px-1.5 text-[11px] font-medium tabular-nums group-data-[collapsible=icon]:hidden", toneClass[tone])}
    >
      {count > MAX_SHOWN ? `${MAX_SHOWN}+` : count}
    </span>
  );
}

function collectEndpoints(items: ConsoleMenuItem[], into: Set<string>) {
  for (const item of items) {
    if (item.badge) into.add(item.badge.endpoint);
    collectEndpoints(item.children, into);
  }
}

/**
 * Loads every badge endpoint in the menu once (deduplicated), then refreshes on an interval.
 * A failing endpoint simply shows no badge.
 */
export function useBadgeCounts(sections: ConsoleSection[] | undefined) {
  const endpoints = useMemo(() => {
    const found = new Set<string>();
    for (const section of sections ?? []) collectEndpoints(section.items, found);
    return [...found].sort();
  }, [sections]);
  const key = endpoints.join("|");
  const [counts, setCounts] = useState<Record<string, number>>({});
  useEffect(() => {
    if (!key) return;
    const list = key.split("|");
    const controller = new AbortController();
    const load = () =>
      list.forEach((endpoint) =>
        fetchBadgeCount(endpoint, controller.signal)
          .then((count) => setCounts((current) => (current[endpoint] === count ? current : { ...current, [endpoint]: count })))
          .catch(() => undefined),
      );
    load();
    const timer = window.setInterval(load, BADGE_REFRESH_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [key]);
  return counts;
}

/** Sum of an item tree's badges and the strongest tone, for a parent row (section or submenu). */
export function rollUp(items: ConsoleMenuItem[], counts: Record<string, number>): { count: number; tone: BadgeTone } {
  let count = 0;
  let tone: BadgeTone = "default";
  const visit = (list: ConsoleMenuItem[]) => {
    for (const item of list) {
      const value = item.badge ? counts[item.badge.endpoint] ?? 0 : 0;
      if (value > 0) {
        count += value;
        if (toneRank[item.badge!.tone] > toneRank[tone]) tone = item.badge!.tone;
      }
      visit(item.children);
    }
  };
  visit(items);
  return { count, tone };
}
