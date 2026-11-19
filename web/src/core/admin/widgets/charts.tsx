"use client";

import { useId, useMemo } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { useTween } from "@/hooks/use-tween";
import { useT } from "@/core/i18n/provider";
import { formatCompact, formatDay, formatNumber } from "@/core/lib/format";
import type { ChartData } from "../console-types";

/** Series colours rotate through the theme's chart tokens. */
const CHART_TOKENS = 5;
/** About this many x-axis labels, whatever the range length. */
const X_TICKS = 6;
const TWEEN_MS = 700;

type Kind = "area_chart" | "line_chart" | "bar_chart";

const numeric = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : 0);

/**
 * Generic time-series chart for Overview widgets (area, line or bar). Values glide from the
 * previous range to the new one (tween), like the source Overview; recharts' own animation
 * is off so the motion is the same for every chart type.
 */
export function SeriesChart({ kind, data }: { kind: Kind; data: ChartData }) {
  const t = useT();
  const reduced = useReducedMotion();
  const gradient = `widget-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const keys = data.series.map((series) => series.key);
  const flat = data.points.flatMap((point) => keys.map((key) => numeric(point[key])));
  const tweened = useTween(flat, { duration: TWEEN_MS, disabled: reduced });
  const rows = data.points.map((point, index) => ({
    x: String(point.x),
    ...Object.fromEntries(keys.map((key, column) => [key, tweened[index * keys.length + column] ?? 0])),
  }));
  const config = useMemo<ChartConfig>(
    () =>
      Object.fromEntries(
        data.series.map((series, index) => [series.key, { label: t.dynamic(series.label, series.label || series.key), color: `var(--chart-${(index % CHART_TOKENS) + 1})` }]),
      ),
    [data.series, t],
  );
  const multiple = data.series.length > 1;
  const grid = <CartesianGrid vertical={false} strokeDasharray="3 5" stroke="var(--border)" />;
  const xAxis = (
    <XAxis
      dataKey="x"
      axisLine={false}
      tickLine={false}
      tickMargin={10}
      interval={Math.max(0, Math.ceil(rows.length / X_TICKS) - 1)}
      tickFormatter={(value: string) => formatDay(String(value), t.locale)}
    />
  );
  const yAxis = <YAxis axisLine={false} tickLine={false} width={48} allowDecimals={false} tickFormatter={(value: number) => formatCompact(value, t.locale)} />;
  const tooltip = (
    <ChartTooltip
      content={
        <ChartTooltipContent
          labelFormatter={(value) => formatDay(String(value), t.locale)}
          formatter={(value, name) => (
            <>
              <span className="text-muted-foreground">{config[String(name)]?.label}</span>
              <span className="ml-3 font-medium tabular-nums">{formatNumber(Math.round(Number(value)), t.locale)}</span>
            </>
          )}
        />
      }
    />
  );
  const legend = multiple ? <ChartLegend content={<ChartLegendContent />} /> : null;
  const margin = { top: 12, right: 12, left: -12, bottom: 4 };
  return (
    <ChartContainer config={config} className="!aspect-auto h-[240px] w-full">
      {kind === "bar_chart" ? (
        <BarChart data={rows} margin={margin} accessibilityLayer>
          {grid}
          {xAxis}
          {yAxis}
          {tooltip}
          {keys.map((key) => (
            <Bar key={key} dataKey={key} fill={`var(--color-${key})`} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          ))}
          {legend}
        </BarChart>
      ) : kind === "line_chart" ? (
        <LineChart data={rows} margin={margin} accessibilityLayer>
          {grid}
          {xAxis}
          {yAxis}
          {tooltip}
          {keys.map((key) => (
            <Line key={key} type="monotone" dataKey={key} stroke={`var(--color-${key})`} strokeWidth={2} dot={rows.length === 1 ? { r: 4 } : false} isAnimationActive={false} />
          ))}
          {legend}
        </LineChart>
      ) : (
        <AreaChart data={rows} margin={margin} accessibilityLayer>
          <defs>
            {keys.map((key) => (
              <linearGradient key={key} id={`${gradient}-${key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={`var(--color-${key})`} stopOpacity={0.36} />
                <stop offset="55%" stopColor={`var(--color-${key})`} stopOpacity={0.18} />
                <stop offset="100%" stopColor={`var(--color-${key})`} stopOpacity={0.06} />
              </linearGradient>
            ))}
          </defs>
          {grid}
          {xAxis}
          {yAxis}
          {tooltip}
          {keys.map((key) => (
            <Area key={key} type="monotone" dataKey={key} stroke={`var(--color-${key})`} fill={`url(#${gradient}-${key})`} strokeWidth={2} dot={rows.length === 1 ? { r: 4 } : false} isAnimationActive={false} />
          ))}
          {legend}
        </AreaChart>
      )}
    </ChartContainer>
  );
}
