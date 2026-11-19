"use client";

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** Slide duration; must match the animation in globals.css (.sidebar-menu-slider). */
const SLIDE_MS = 260;

/**
 * Nested sidebar menus: changing `value` slides the new panel in (forward when `depth` grows,
 * back when it shrinks) while the old one slides out. Focus follows into the new panel.
 */
export function SidebarMenuSlider<T extends string | null>({
  value,
  depth,
  children,
}: {
  value: T;
  depth: number;
  children: (value: T) => ReactNode;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [frame, setFrame] = useState({
    value,
    depth,
    previous: undefined as T | undefined,
    direction: "forward",
    revision: 0,
  });
  if (frame.value !== value) {
    setFrame({
      value,
      depth,
      previous: frame.value,
      direction: depth < frame.depth ? "back" : "forward",
      revision: frame.revision + 1,
    });
  }

  useLayoutEffect(() => {
    const outgoing = container.current?.querySelector('[data-menu-state="outgoing"]');
    if (outgoing?.contains(document.activeElement)) {
      container.current?.querySelector<HTMLElement>('[data-menu-state="current"] button, [data-menu-state="current"] a')?.focus({ preventScroll: true });
    }
  }, [frame.revision]);

  useEffect(() => {
    if (frame.previous === undefined) return;
    const timer = window.setTimeout(() => {
      setFrame((current) => (current.revision === frame.revision ? { ...current, previous: undefined } : current));
    }, window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : SLIDE_MS);
    return () => window.clearTimeout(timer);
  }, [frame.previous, frame.revision]);

  const panels = frame.previous === undefined ? [frame.value] : [frame.previous, frame.value];
  return (
    <div ref={container} className="sidebar-menu-slider relative isolate min-w-0" data-direction={frame.direction} data-moving={frame.previous !== undefined}>
      {panels.map((panel) => {
        const outgoing = panel !== frame.value;
        return (
          <div
            key={panel ?? "main"}
            data-menu-panel={panel ?? "main"}
            data-menu-state={outgoing ? "outgoing" : "current"}
            aria-hidden={outgoing || undefined}
            inert={outgoing || undefined}
            className={outgoing ? "pointer-events-none absolute inset-x-0 top-0" : "relative min-w-0"}
          >
            {children(panel)}
          </div>
        );
      })}
    </div>
  );
}
