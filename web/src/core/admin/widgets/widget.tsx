"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { useT } from "@/core/i18n/provider";
import type { DateRange } from "@/core/lib/date-range";
import { cn } from "@/lib/utils";
import { fetchWidgetData } from "../console-api";
import type { ChartData, KpiData, ListData, OverviewWidget, TodoData, WidgetSize } from "../console-types";
import { KpiWidget } from "./kpi";
import { ListWidget, TodoWidget } from "./lists";
import { WidgetCard, WidgetEmpty, WidgetError, WidgetSkeleton } from "./widget-card";

// recharts is large; only Overview pages that show a chart load it.
const SeriesChart = dynamic(() => import("./charts").then((module) => module.SeriesChart), {
  ssr: false,
  loading: () => <WidgetSkeleton type="area_chart" />,
});

/** Grid footprint on the Overview (4 columns from lg, 2 from md, 1 on phones). */
export const widgetSpan: Record<WidgetSize, string> = {
  sm: "col-span-1",
  md: "col-span-1 md:col-span-2",
  lg: "col-span-1 md:col-span-2 lg:col-span-3",
  full: "col-span-full",
};

type Loaded = { key: string; data?: unknown; failed?: boolean };

/** Fetches one widget's data for the range with its own loading / empty / error states. */
export function Widget({ widget, range }: { widget: OverviewWidget; range: DateRange }) {
  const t = useT();
  const key = `${widget.endpoint}|${range.from}|${range.to}`;
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState<Loaded>();
  // Keep the previous data on screen while a new range loads, so charts glide instead of flashing.
  const [last, setLast] = useState<unknown>();

  useEffect(() => {
    const controller = new AbortController();
    fetchWidgetData(widget.type, widget.endpoint, range, controller.signal)
      .then((data) => {
        setLoaded({ key, data });
        setLast(data);
      })
      .catch(() => {
        if (!controller.signal.aborted) setLoaded({ key, failed: true });
      });
    return () => controller.abort();
    // `range` is represented by `key`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, widget.type, attempt]);

  const current = loaded?.key === key ? loaded : undefined;
  const data = current?.data ?? last;
  const title = t.dynamic(widget.title, widget.title_default);

  let body: React.ReactNode;
  if (current?.failed) body = <WidgetError retry={() => setAttempt((value) => value + 1)} />;
  else if (data === undefined) body = <WidgetSkeleton type={widget.type} />;
  else if (widget.type === "kpi") body = <KpiWidget data={data as KpiData} />;
  else if (widget.type === "list") body = (data as ListData).items.length ? <ListWidget data={data as ListData} /> : <WidgetEmpty type="list" />;
  else if (widget.type === "todo") body = (data as TodoData).items.length ? <TodoWidget data={data as TodoData} /> : <WidgetEmpty type="todo" />;
  else body = (data as ChartData).points.length ? <SeriesChart kind={widget.type} data={data as ChartData} /> : <WidgetEmpty type={widget.type} />;

  return (
    <WidgetCard title={title} className={cn(widgetSpan[widget.size], widget.type === "kpi" && "min-h-[142px]")} aside={!current && data !== undefined ? <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-muted-foreground/50" /> : undefined}>
      <div data-widget-type={widget.type} data-widget-id={widget.id} aria-busy={!current || undefined} className="min-w-0">
        {body}
      </div>
    </WidgetCard>
  );
}
