"use client";
import { useSyncExternalStore } from "react";

// Inlined at build time into both the server and browser bundles, so the first render always matches.
const BUILD_YEAR = Number(process.env.NEXT_PUBLIC_BUILD_YEAR) || new Date().getUTCFullYear();

const noChanges = () => () => {};
const browserYear = () => new Date().getUTCFullYear();

/** The current year, corrected in the browser after the first render so pages built last year still show this year. */
export function useCurrentYear(): number {
  return useSyncExternalStore(noChanges, browserYear, () => BUILD_YEAR);
}
