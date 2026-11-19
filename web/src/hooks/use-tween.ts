"use client";

import { useEffect, useRef, useState } from "react";

const ease = (t: number) =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

/** Stretch a series to `length` points by linear interpolation (shape-preserving). */
function resample(values: number[], length: number) {
  if (values.length === length) return values;
  if (!values.length) return Array<number>(length).fill(0);
  return Array.from({ length }, (_, i) => {
    const pos = length === 1 ? 0 : (i * (values.length - 1)) / (length - 1);
    const lo = Math.floor(pos);
    const hi = Math.min(values.length - 1, lo + 1);
    return values[lo] + (values[hi] - values[lo]) * (pos - lo);
  });
}

/**
 * Animates numbers from what is currently on screen to `target` (presentation
 * only; callers render exact values once settled). A new target mid-flight
 * continues from the in-between frame, and series of different lengths are
 * resampled so curves morph instead of resetting.
 */
export function useTween(target: number[], { duration = 700, disabled = false, initial }: { duration?: number; disabled?: boolean; initial?: number[] } = {}) {
  const key = target.join(",");
  // `initial` lets a value count up from somewhere else (for example 0) the first time it appears.
  const [shown, setShown] = useState(initial ?? target);
  const current = useRef(initial ?? target);
  useEffect(() => {
    const goal = key ? key.split(",").map(Number) : [];
    const from = resample(current.current, goal.length);
    if (disabled) {
      current.current = goal;
      return;
    }
    const start = performance.now();
    let frame = requestAnimationFrame(function step(now) {
      const t = Math.min(1, (now - start) / duration);
      const k = ease(t);
      const next = t === 1 ? goal : goal.map((value, i) => from[i] + (value - from[i]) * k);
      current.current = next;
      setShown(next);
      if (t < 1) frame = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(frame);
  }, [key, disabled, duration]);
  if (disabled) return target;
  return shown.length === target.length ? shown : resample(shown, target.length);
}
