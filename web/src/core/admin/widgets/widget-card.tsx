"use client";

import { CircleAlert } from "lucide-react";
import { RetryButton } from "@/components/ui/retry-button";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/core/i18n/provider";
import { cn } from "@/lib/utils";
import type { WidgetType } from "../console-types";

/** Shared frame for Overview widgets: bordered panel, heading, and the three non-data states. */
export function WidgetCard({ title, aside, className, children }: { title: string; aside?: React.ReactNode; className?: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className={cn("flex min-w-0 flex-col rounded-lg border bg-card p-4 text-card-foreground", className)}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <h2 className="min-w-0 text-[13px] leading-5 font-semibold">{title}</h2>
        {aside}
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>
    </section>
  );
}

const skeletonHeight: Record<WidgetType, string> = {
  kpi: "h-[72px]",
  area_chart: "h-[240px]",
  line_chart: "h-[240px]",
  bar_chart: "h-[240px]",
  list: "h-[200px]",
  todo: "h-[160px]",
};

export function WidgetSkeleton({ type }: { type: WidgetType }) {
  const t = useT();
  return <Skeleton role="status" aria-label={t("common.loading")} className={cn("w-full", skeletonHeight[type])} />;
}

export function WidgetEmpty({ type }: { type: WidgetType }) {
  const t = useT();
  return <div className={cn("grid place-items-center text-center text-xs text-muted-foreground", type === "kpi" ? "min-h-[72px]" : "min-h-[160px]")}>{t("admin.widgets.empty")}</div>;
}

export function WidgetError({ retry }: { retry: () => void }) {
  const t = useT();
  return (
    <div role="alert" className="flex min-h-[72px] flex-col items-start justify-center gap-2 text-xs text-muted-foreground">
      <span className="flex items-center gap-1.5">
        <CircleAlert className="size-3.5 text-failure" aria-hidden="true" />
        {t("admin.widgets.error")}
      </span>
      <RetryButton size="sm" variant="outline" retry={retry} label={t("admin.widgets.retry")} />
    </div>
  );
}
