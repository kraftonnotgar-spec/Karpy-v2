"use client";
import { useMemo } from "react";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { useTween } from "@/hooks/use-tween";

export type FigureParts = { prefix: string; suffix: string; value: number; decimals: number; grouped: boolean };

/** Splits a formatted figure ("USD 6,218", "80%", "0.68%") into its number and the text around it, using the locale's separators. */
export function parseFigure(text: string, locale?: string): FigureParts | null {
  const parts = new Intl.NumberFormat(locale).formatToParts(12345.6);
  const group = parts.find((part) => part.type === "group")?.value ?? ",";
  const decimal = parts.find((part) => part.type === "decimal")?.value ?? ".";
  const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\\s]/g, (character) => (/\s/.test(character) ? "\\s" : "\\" + character));
  const match = new RegExp(`-?\\d(?:\\d|${escape(group)}(?=\\d))*(?:${escape(decimal)}\\d+)?`).exec(text);
  if (!match) return null;
  const raw = match[0];
  const [whole, fraction = ""] = raw.split(decimal);
  const value = Number(whole.split(group).join("") + (fraction ? "." + fraction : ""));
  if (!Number.isFinite(value)) return null;
  return { prefix: text.slice(0, match.index), suffix: text.slice(match.index + raw.length), value, decimals: fraction.length, grouped: raw.includes(group) || Math.abs(value) < 1000 };
}

export function formatFigure(parts: FigureParts, value: number, locale?: string): string {
  return parts.prefix + new Intl.NumberFormat(locale, { minimumFractionDigits: parts.decimals, maximumFractionDigits: parts.decimals, useGrouping: parts.grouped }).format(value) + parts.suffix;
}

/**
 * Counts a formatted figure from the previous value to the new one (from 0 the first time).
 * In-between frames are display only; once settled the exact formatted text is shown.
 */
export function AnimatedFigure({ text, locale, duration = 700 }: { text: string; locale?: string; duration?: number }) {
  const reduced = useReducedMotion();
  const parts = useMemo(() => parseFigure(text, locale), [text, locale]);
  const target = parts?.value ?? 0;
  const [shown] = useTween([target], { duration, disabled: reduced || !parts, initial: [0] });
  if (!parts || shown === target) return <>{text}</>;
  return <span className="tabular-nums">{formatFigure(parts, shown, locale)}</span>;
}
