"use client";

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { AnimatedFigure } from "@/core/components/animated-figure";
import { useT } from "@/core/i18n/provider";
import { formatNumber, percentChange } from "@/core/lib/format";
import type { KpiData } from "../console-types";

export function formatKpi(data: KpiData, locale: string) {
  if (data.format === "percent") return formatNumber(data.value / 100, locale, { style: "percent", maximumFractionDigits: 2 });
  if (data.format === "currency" && data.currency)
    return formatNumber(data.value, locale, { style: "currency", currency: data.currency, currencyDisplay: "code", maximumFractionDigits: 2 });
  return formatNumber(data.value, locale);
}

/** One stat: big animated value and the change against the previous equal-length period. */
export function KpiWidget({ data }: { data: KpiData }) {
  const t = useT();
  const text = formatKpi(data, t.locale);
  const change = percentChange(data.value, data.previous);
  const Trend = change === null || change === 0 ? Minus : change > 0 ? ArrowUpRight : ArrowDownRight;
  const tone = change === null || change === 0 ? "text-muted-foreground" : change > 0 ? "text-success" : "text-failure";
  return (
    <div className="flex min-w-0 flex-col">
      <p className="text-[24px] leading-8 font-semibold tabular-nums [overflow-wrap:anywhere]" title={text}>
        <AnimatedFigure text={text} locale={t.locale} />
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px]">
        <span className={`inline-flex items-center ${tone}`}>
          <Trend className="mr-0.5 size-3" aria-hidden="true" />
          {change === null ? t("admin.widgets.noComparison") : `${formatNumber(Math.abs(change), t.locale, { maximumFractionDigits: 1 })}%`}
        </span>
        {change !== null && <span className="text-muted-foreground">{t("admin.widgets.vsPrevious")}</span>}
      </div>
    </div>
  );
}
