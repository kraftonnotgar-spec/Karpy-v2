"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Ban,
  Bell,
  CircleAlert,
  Clock,
  Inbox,
  KeyRound,
  Lock,
  LockKeyhole,
  RefreshCw,
  SearchX,
  ShieldAlert,
  WifiOff,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { RetryButton } from "@/components/ui/retry-button";
import { Skeleton } from "@/components/ui/skeleton";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import type { MessageKey } from "@/core/i18n";
import { useT } from "@/core/i18n/provider";
import type { SafeError } from "@/core/lib/api";
import { cn } from "@/lib/utils";

/** Table-shaped placeholder; row height matches loaded rows to avoid shifts. */
export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  const t = useT();
  return (
    <div role="status" aria-label={t("common.loading")} className="flex flex-col">
      <div className="hidden h-10 items-center gap-6 border-b px-4 md:flex">
        {[28, 14, 14, 16, 18].map((width, i) => (
          <Skeleton key={i} className="h-3" style={{ width: `${width}%` }} />
        ))}
      </div>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex h-16 items-center gap-6 border-b px-4 last:border-0 md:h-[53px]">
          <Skeleton className="h-3.5 w-1/3 md:w-[28%]" />
          <Skeleton className="hidden h-5 w-[14%] md:block" />
          <Skeleton className="ml-auto h-5 w-20 md:ml-0 md:w-[14%]" />
          <Skeleton className="hidden h-3.5 w-[16%] md:block" />
          <Skeleton className="hidden h-3.5 w-[18%] md:block" />
        </div>
      ))}
    </div>
  );
}

/** Page placeholder: heading, four summary tiles and a table, revealed only after a short delay. */
export function PageLoading() {
  const t = useT();
  return (
    <div role="status" aria-label={t("common.loadingPage")} aria-busy="true" data-workspace-loading className="flex min-w-0 flex-col gap-4">
      <div aria-hidden="true" className="flex h-10 items-center justify-between gap-3">
        <Skeleton className="h-5 w-36" />
        <Skeleton className="h-9 w-24" />
      </div>
      <div aria-hidden="true" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="flex min-h-[124px] flex-col gap-4 rounded-lg border p-4">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="h-7 w-32 max-w-full" />
            <Skeleton className="h-3 w-24" />
          </div>
        ))}
      </div>
      <div aria-hidden="true" className="rounded-lg border">
        <TableSkeleton rows={5} />
      </div>
    </div>
  );
}

const emptyIcons = {
  alert: CircleAlert,
  ban: Ban,
  bell: Bell,
  clock: Clock,
  inbox: Inbox,
  key: KeyRound,
  lock: Lock,
  "lock-keyhole": LockKeyhole,
  refresh: RefreshCw,
  search: SearchX,
  "shield-alert": ShieldAlert,
  "wifi-off": WifiOff,
} as const;

export type EmptyIconName = keyof typeof emptyIcons;

export function EmptyState({
  title,
  description,
  icon = "inbox",
  children,
  className,
}: {
  title: string;
  description: string;
  icon?: EmptyIconName;
  children?: React.ReactNode;
  className?: string;
}) {
  const Icon = emptyIcons[icon];
  return (
    <Empty className={cn("min-h-52", className)}>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Icon />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
      {children && <EmptyContent>{children}</EmptyContent>}
    </Empty>
  );
}

type ErrorCopy = { icon: EmptyIconName; key: "sessionExpired" | "forbidden" | "notFound" | "conflict" | "tooMany" | "timeout" | "unavailable" | "invalid" | "generic" };

function describe(error: SafeError): ErrorCopy {
  if (error.status === 401) return { icon: "lock-keyhole", key: "sessionExpired" };
  if (error.status === 403) return { icon: "lock-keyhole", key: "forbidden" };
  if (error.status === 404) return { icon: "search", key: "notFound" };
  if (error.status === 409) return { icon: "alert", key: "conflict" };
  if (error.status === 422) return { icon: "alert", key: "invalid" };
  if (error.status === 429) return { icon: "clock", key: "tooMany" };
  if (error.status === 504 || error.code === "timeout") return { icon: "clock", key: "timeout" };
  if (error.status === 503) return { icon: "wifi-off", key: "unavailable" };
  return { icon: "alert", key: "generic" };
}

/** Safe, correlated failure. Never shows upstream messages. */
export function ErrorState({
  error,
  retry,
  signInHref = "/sign-in",
  className,
}: {
  error: SafeError;
  retry?: () => void;
  signInHref?: string;
  className?: string;
}) {
  const t = useT();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!error.retryAt) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [error.retryAt]);
  const remaining = error.retryAt ? Math.max(0, Math.ceil((error.retryAt - now) / 1000)) : 0;
  const { icon, key } = describe(error);
  const description =
    key === "tooMany" && remaining ? t("errors.tooMany.retryIn", { seconds: remaining }) : t(`errors.${key}.description` as MessageKey);
  return (
    <EmptyState icon={icon} title={t(`errors.${key}.title` as MessageKey)} description={description} className={className}>
      {error.requestId && (
        <p className="max-w-full font-mono text-xs break-all text-muted-foreground">{t("common.supportReference", { id: error.requestId })}</p>
      )}
      <div className="flex flex-wrap justify-center gap-2">
        {error.status === 401 ? (
          <Button asChild>
            <Link href={signInHref}>{t("common.signIn")}</Link>
          </Button>
        ) : (
          retry && <RetryButton variant="outline" disabled={remaining > 0} retry={retry} label={t("common.tryAgain")} />
        )}
      </div>
    </EmptyState>
  );
}
