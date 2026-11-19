"use client";

import { useEffect, useMemo, useState } from "react";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { PageHeader } from "@/core/components/page-header";
import { EmptyState, ErrorState } from "@/core/components/states";
import { useT } from "@/core/i18n/provider";
import { toSafeError, type SafeError } from "@/core/lib/api";
import { DATE_RANGE_PRESETS, DEFAULT_DATE_RANGE_PRESET, presetRange, type DateRangePreset } from "@/core/lib/date-range";
import { formatDay } from "@/core/lib/format";
import { fetchConsoleWidgets } from "./console-api";
import type { OverviewWidget } from "./console-types";
import { Widget, widgetSpan } from "./widgets/widget";
import { WidgetCard, WidgetSkeleton } from "./widgets/widget-card";

/**
 * Admin Overview: composed at runtime from the widgets active plugins register
 * (GET /api/admin/console/widgets). Each widget loads its own data for the selected range.
 */
export function AdminOverview() {
  const t = useT();
  const [widgets, setWidgets] = useState<OverviewWidget[]>();
  const [error, setError] = useState<SafeError>();
  const [attempt, setAttempt] = useState(0);
  const [preset, setPreset] = useState<DateRangePreset>(DEFAULT_DATE_RANGE_PRESET);
  const range = useMemo(() => presetRange(preset), [preset]);

  useEffect(() => {
    const controller = new AbortController();
    fetchConsoleWidgets(controller.signal)
      .then((value) => {
        setWidgets([...value].sort((a, b) => a.order - b.order || a.id.localeCompare(b.id)));
        setError(undefined);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(toSafeError(reason));
      });
    return () => controller.abort();
  }, [attempt]);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("admin.overview.title")} description={t("admin.overview.description")}>
        <span className="hidden text-[11px] text-muted-foreground sm:inline">
          {t("admin.range.fromTo", { from: formatDay(range.from, t.locale), to: formatDay(range.to, t.locale) })}
        </span>
        <ToggleGroup
          type="single"
          size="sm"
          variant="outline"
          value={String(preset)}
          aria-label={t("admin.range.label")}
          onValueChange={(value) => value && setPreset(Number(value) as DateRangePreset)}
        >
          {DATE_RANGE_PRESETS.map((days) => (
            <ToggleGroupItem key={days} value={String(days)} className="px-2.5 text-[12px]">
              {t("admin.range.days", { days })}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </PageHeader>
      {error ? (
        <div className="rounded-lg border">
          <ErrorState error={error} retry={() => setAttempt((value) => value + 1)} className="min-h-80" />
        </div>
      ) : !widgets ? (
        <div className="grid grid-flow-row-dense grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4" aria-busy="true">
          {(["sm", "sm", "sm", "sm", "md", "md"] as const).map((size, index) => (
            <WidgetCard key={index} title="" className={widgetSpan[size]}>
              <WidgetSkeleton type={size === "sm" ? "kpi" : "area_chart"} />
            </WidgetCard>
          ))}
        </div>
      ) : widgets.length === 0 ? (
        <div className="rounded-lg border">
          <EmptyState icon="inbox" title={t("admin.widgets.none")} description={t("admin.widgets.noneDescription")} className="min-h-80" />
        </div>
      ) : (
        <div className="grid grid-flow-row-dense grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          {widgets.map((widget) => (
            <Widget key={widget.id} widget={widget} range={range} />
          ))}
        </div>
      )}
    </div>
  );
}
