"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { adminHref } from "@/core/config/admin-path";
import { useT } from "@/core/i18n/provider";
import { formatNumber } from "@/core/lib/format";
import type { ListData, TodoData } from "../console-types";

/** Admin routes from plugins ("/admin/…") follow the configured admin base path. */
const resolveHref = (href: string) => (href.startsWith("/admin") ? adminHref(href) : href);

/** Recent items: title, optional subtitle and a right-aligned meta (time, amount, status). */
export function ListWidget({ data }: { data: ListData }) {
  return (
    <ul className="-mx-1 flex flex-col divide-y">
      {data.items.map((item) => {
        const body = (
          <>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-[13px]">{item.title}</span>
              {item.subtitle && <span className="truncate text-[11px] text-muted-foreground">{item.subtitle}</span>}
            </span>
            {item.meta && <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums">{item.meta}</span>}
          </>
        );
        return (
          <li key={item.id}>
            {item.href ? (
              <Link href={resolveHref(item.href)} prefetch={false} className="flex min-h-11 items-center gap-3 rounded-md px-1 py-2 hover:bg-muted/50">
                {body}
              </Link>
            ) : (
              <div className="flex min-h-11 items-center gap-3 px-1 py-2">{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Things waiting for an admin: label, count and a link to the queue. */
export function TodoWidget({ data }: { data: TodoData }) {
  const t = useT();
  return (
    <ul className="-mx-1 flex flex-col divide-y">
      {data.items.map((item) => (
        <li key={item.id}>
          <Link href={resolveHref(item.href)} prefetch={false} className="flex min-h-11 items-center gap-3 rounded-md px-1 py-2 text-[13px] hover:bg-muted/50">
            <span className="min-w-0 flex-1 truncate">{t.dynamic(item.label, item.label)}</span>
            <span
              data-badge-tone={item.count ? "attention" : "default"}
              className={item.count ? "inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-warning-surface px-1.5 text-[11px] font-medium text-warning tabular-nums" : "text-[11px] text-muted-foreground tabular-nums"}
            >
              {formatNumber(item.count, t.locale)}
            </span>
            <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          </Link>
        </li>
      ))}
    </ul>
  );
}
