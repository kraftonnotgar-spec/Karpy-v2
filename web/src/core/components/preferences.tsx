"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";
import {
  defaultThemePolicy,
  resolveTheme,
  THEME_POLICY_STORAGE_KEY,
  THEME_STORAGE_KEY,
  type ThemePolicy,
} from "@/core/lib/theme-policy";

// Per-viewer presentation preferences only. Storage can be unavailable
// (private mode, blocked site data), so an in-memory value always wins.
export type Theme = "light" | "dark" | "system";
const memory = new Map<string, string>();
const listeners = new Set<() => void>();
let themePolicy = defaultThemePolicy;

function read(key: string) {
  if (memory.has(key)) return memory.get(key)!;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, value: string) {
  memory.set(key, value);
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* Preference stays in memory for this tab. */
  }
  listeners.forEach((listener) => listener());
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  window.addEventListener("storage", listener);
  media.addEventListener("change", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
    media.removeEventListener("change", listener);
  };
}

function themeSnapshot(): Theme {
  const value = read(THEME_STORAGE_KEY);
  return value === "light" || value === "dark" || value === "system" ? value : themePolicy.default_theme;
}
const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, themeSnapshot, () => "system");
  const dark = useSyncExternalStore(
    subscribe,
    () => resolveTheme(read(THEME_STORAGE_KEY), themePolicy, systemDark()) === "dark",
    () => false,
  );
  const canToggle = useSyncExternalStore(subscribe, () => themePolicy.theme_mode === "both", () => true);
  const setTheme = useCallback((value: Theme) => {
    if (themePolicy.theme_mode === "both" || value === themePolicy.theme_mode) write(THEME_STORAGE_KEY, value);
  }, []);
  return { theme: theme as Theme, resolved: dark ? "dark" : "light", setTheme, canToggle };
}

// Reads real storage/media state, never React's hydration snapshot, so the
// class set by the pre-paint script is not briefly undone.
function applyTheme() {
  document.documentElement.classList.toggle("dark", resolveTheme(read(THEME_STORAGE_KEY), themePolicy, systemDark()) === "dark");
}

/** Keeps the html class in sync with preference, other tabs and the OS. */
export function ThemeSync({ policy }: { policy?: ThemePolicy }) {
  useEffect(() => {
    themePolicy = policy ?? defaultThemePolicy;
    if (!policy) {
      try {
        const cached = JSON.parse(localStorage.getItem(THEME_POLICY_STORAGE_KEY) ?? "null");
        if (cached && ["light", "dark"].includes(cached.default_theme) && ["both", "light", "dark"].includes(cached.theme_mode)) themePolicy = cached;
      } catch {
        /* Use the default policy when the cache is unavailable. */
      }
    }
    if (policy) {
      try {
        localStorage.setItem(THEME_POLICY_STORAGE_KEY, JSON.stringify(policy));
      } catch {
        /* Presentation cache is optional. */
      }
    }
    listeners.forEach((listener) => listener());
    applyTheme();
  }, [policy]);
  useEffect(() => {
    applyTheme();
    return subscribe(applyTheme);
  }, []);
  return null;
}
