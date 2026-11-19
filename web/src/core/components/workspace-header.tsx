"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar";
import { useT } from "@/core/i18n/provider";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "./theme-toggle";

export type Crumb = { label: string; href?: string };

function HeaderNavigationTrigger() {
  const t = useT();
  const { open, openMobile, isMobile } = useSidebar();
  if (isMobile ? openMobile : open) return null;
  return <SidebarTrigger aria-label={t("common.toggleNavigation")} title={t("common.toggleNavigation")} variant="outline" className="size-9 shrink-0" />;
}

/** Sticky workspace header: navigation trigger, breadcrumb trail, actions and theme toggle. */
export function WorkspaceHeader({ trail, actions }: { trail: Crumb[]; actions?: React.ReactNode }) {
  const t = useT();
  return (
    <header data-workspace-header className="workspace-surface sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 border-b px-3 sm:px-5 lg:px-6">
      <HeaderNavigationTrigger />
      <nav aria-label={t("common.breadcrumb")} className="flex min-w-0 flex-1 items-center gap-1.5 text-[13px]">
        {trail.map((crumb, index) => {
          const last = index === trail.length - 1;
          return (
            <span key={`${index}-${crumb.label}`} className={cn("flex min-w-0 items-center gap-1.5", !last && "hidden sm:flex")}>
              {index > 0 && <ChevronRight aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />}
              {!last && crumb.href ? (
                <Link href={crumb.href} className="min-w-0 truncate text-muted-foreground hover:text-foreground">
                  {crumb.label}
                </Link>
              ) : (
                <span aria-current={last ? "page" : undefined} className={cn("min-w-0 truncate", last ? "text-foreground" : "text-muted-foreground")}>
                  {crumb.label}
                </span>
              )}
            </span>
          );
        })}
      </nav>
      <div className="flex shrink-0 items-center gap-1.5">
        {actions}
        <ThemeToggle />
      </div>
    </header>
  );
}

/** Keyboard users jump past the sidebar. */
export function SkipToContent() {
  const t = useT();
  return (
    <a href="#content" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-background focus:p-3">
      {t("common.skipToContent")}
    </a>
  );
}
