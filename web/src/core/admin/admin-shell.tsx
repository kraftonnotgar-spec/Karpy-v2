"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ChevronRight, LogOut, ShieldCheck } from "lucide-react";
import { RetryButton } from "@/components/ui/retry-button";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { Brand, BrandMark } from "@/core/components/brand-mark";
import { Icon } from "@/core/components/icon";
import { SidebarMenuSlider } from "@/core/components/sidebar-menu-slider";
import { SkipToContent, WorkspaceHeader, type Crumb } from "@/core/components/workspace-header";
import { adminHref } from "@/core/config/admin-path";
import type { NavGroup } from "@/core/features/navigation";
import { useT } from "@/core/i18n/provider";
import { toSafeError, type SafeError } from "@/core/lib/api";
import { toast } from "@/core/lib/notify";
import { adminLogout, fetchAdminStatus, fetchConsoleMenu } from "./console-api";
import type { ConsoleMenuItem, ConsoleSection } from "./console-types";
import { MenuCountBadge, rollUp, useBadgeCounts } from "./menu-badge";

const SIGN_IN_ROUTE = "/admin/sign-in";

/** The registry menu loaded by the shell, for pages that need labels from it. */
const ConsoleMenuContext = createContext<ConsoleSection[] | undefined>(undefined);

/** Active when the path is the item's route or below it. */
function routeActive(path: string, route: string) {
  if (!route) return false;
  const href = adminHref(route);
  return path === href || path.startsWith(`${href}/`);
}

/** The chain [section, item, child…] whose route matches the path, or null. */
function findTrail(sections: ConsoleSection[], path: string): { section: ConsoleSection; items: ConsoleMenuItem[] } | null {
  const search = (items: ConsoleMenuItem[], chain: ConsoleMenuItem[]): ConsoleMenuItem[] | null => {
    for (const item of items) {
      const next = [...chain, item];
      const deeper = search(item.children, next);
      if (deeper) return deeper;
      if (routeActive(path, item.route)) return next;
    }
    return null;
  };
  for (const section of sections) {
    const items = search(section.items, []);
    if (items) return { section, items };
  }
  return null;
}

/**
 * Panel stack: [] = Workspace level; [sectionId] = a section's panel; [sectionId, itemId, …]
 * = nested submenus. Each level slides in over the previous one.
 */
type PanelPath = string[];

function panelForPath(sections: ConsoleSection[], path: string): PanelPath {
  const trail = findTrail(sections, path);
  if (!trail) return [];
  // Open the deepest submenu that contains the active item.
  return [trail.section.id, ...trail.items.slice(0, -1).map((item) => item.id)];
}

function resolvePanel(sections: ConsoleSection[], panel: PanelPath) {
  const section = sections.find((value) => value.id === panel[0]);
  if (!section) return null;
  const chain: ConsoleMenuItem[] = [];
  let items = section.items;
  for (const id of panel.slice(1)) {
    const item = items.find((value) => value.id === id);
    if (!item) break;
    chain.push(item);
    items = item.children;
  }
  return { section, chain, items };
}

function AdminSidebar({
  brandName,
  workspace,
  sections,
  menuError,
  retryMenu,
  path,
  signingOut,
  onSignOut,
}: {
  brandName: string;
  workspace: NavGroup[];
  sections: ConsoleSection[] | undefined;
  menuError: SafeError | undefined;
  retryMenu: () => void;
  path: string;
  signingOut: boolean;
  onSignOut: () => void;
}) {
  const t = useT();
  const { isMobile, setOpenMobile, setOpen } = useSidebar();
  const counts = useBadgeCounts(sections);
  const [panel, setPanel] = useState<PanelPath>([]);
  const [syncedFor, setSyncedFor] = useState<string>();
  // When the menu arrives (or the URL changes from outside the sidebar), open the panel
  // that holds the current page, like the source console does.
  const syncKey = sections ? `${path}#${sections.length}` : undefined;
  if (sections && syncKey !== syncedFor) {
    setSyncedFor(syncKey);
    setPanel(panelForPath(sections, path));
  }
  const resolved = sections ? resolvePanel(sections, panel) : null;
  const label = (value: { label: string; label_default: string }) => t.dynamic(value.label, value.label_default);
  const closeOnMobile = () => isMobile && setOpenMobile(false);

  const itemRow = (item: ConsoleMenuItem) => {
    const text = label(item);
    if (item.children.length) {
      const total = rollUp(item.children, counts);
      return (
        <SidebarMenuItem key={item.id}>
          <SidebarMenuButton className="h-10 rounded-md text-[13px]" tooltip={text} isActive={!!findTrail([{ ...resolved!.section, items: [item] }], path)} onClick={() => setPanel([...panel, item.id])}>
            <Icon name={item.icon} />
            <span>{text}</span>
            <MenuCountBadge count={total.count} tone={total.tone} />
            <ChevronRight aria-hidden="true" className="ml-1 group-data-[collapsible=icon]:hidden" />
          </SidebarMenuButton>
        </SidebarMenuItem>
      );
    }
    const active = routeActive(path, item.route);
    return (
      <SidebarMenuItem key={item.id}>
        <SidebarMenuButton asChild className="h-10 rounded-md text-[13px]" isActive={active} tooltip={text}>
          <Link href={adminHref(item.route)} prefetch={false} aria-current={active ? "page" : undefined} onClick={closeOnMobile}>
            <Icon name={item.icon} />
            <span>{text}</span>
            {item.badge && <MenuCountBadge count={counts[item.badge.endpoint]} tone={item.badge.tone} />}
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  };

  const backRow = (text: string, target: PanelPath) => (
    <SidebarGroup>
      <SidebarGroupContent>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton tooltip={text} className="h-10" onClick={() => setPanel(target)}>
              <ArrowLeft />
              <span>{text}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="h-14 justify-center border-b px-4">
        <Link href={adminHref("/admin")} className="flex items-center gap-2.5" onClick={() => setPanel([])}>
          <BrandMark name={brandName} className="hidden group-data-[collapsible=icon]:grid" />
          <Brand name={brandName} suffix={t("admin.consoleName")} className="group-data-[collapsible=icon]:hidden" />
        </Link>
      </SidebarHeader>
      <SidebarContent className="overflow-x-hidden py-3">
        <SidebarMenuSlider value={panel.join("/") || null} depth={panel.length}>
          {() =>
            resolved ? (
              <>
                {backRow(
                  resolved.chain.length ? t("admin.backTo", { label: label(resolved.chain.length > 1 ? resolved.chain[resolved.chain.length - 2] : resolved.section) }) : t("admin.backToWorkspace"),
                  panel.slice(0, -1),
                )}
                <SidebarGroup>
                  <SidebarGroupLabel>{label(resolved.chain.at(-1) ?? resolved.section)}</SidebarGroupLabel>
                  <SidebarGroupContent>
                    <SidebarMenu>{resolved.items.map(itemRow)}</SidebarMenu>
                  </SidebarGroupContent>
                </SidebarGroup>
              </>
            ) : (
              <>
                {workspace.map((group) => (
                  <SidebarGroup key={group.id}>
                    {group.labelKey && <SidebarGroupLabel>{t(group.labelKey)}</SidebarGroupLabel>}
                    <SidebarGroupContent>
                      <SidebarMenu>
                        {group.items.map((item) => {
                          const href = adminHref(item.href);
                          const active = item.matchNested === false ? path === href : path === href || path.startsWith(`${href}/`);
                          const text = t(item.labelKey);
                          return (
                            <SidebarMenuItem key={item.id}>
                              <SidebarMenuButton asChild className="h-10 rounded-md text-[13px]" isActive={active} tooltip={text}>
                                <Link href={href} aria-current={active ? "page" : undefined} onClick={closeOnMobile}>
                                  <Icon name={item.icon} />
                                  <span>{text}</span>
                                </Link>
                              </SidebarMenuButton>
                            </SidebarMenuItem>
                          );
                        })}
                      </SidebarMenu>
                    </SidebarGroupContent>
                  </SidebarGroup>
                ))}
                <SidebarGroup className="mt-3 border-t pt-4">
                  <SidebarGroupContent>
                    {menuError ? (
                      <div className="flex flex-col items-start gap-2 px-2 text-[12px] text-muted-foreground group-data-[collapsible=icon]:hidden">
                        <p>{t("admin.menuUnavailable")}</p>
                        <RetryButton size="sm" variant="outline" retry={retryMenu} label={t("common.tryAgain")} />
                      </div>
                    ) : !sections ? (
                      <div aria-busy="true" className="flex flex-col gap-2 px-2">
                        {Array.from({ length: 4 }, (_, index) => (
                          <Skeleton key={index} className="h-9 w-full" />
                        ))}
                      </div>
                    ) : (
                      <SidebarMenu>
                        {sections.map((section) => {
                          const text = label(section);
                          const total = rollUp(section.items, counts);
                          const active = !!findTrail([section], path);
                          return (
                            <SidebarMenuItem key={section.id}>
                              <SidebarMenuButton
                                tooltip={text}
                                className="h-11 text-[13px]"
                                isActive={active}
                                onClick={() => {
                                  setOpen(true);
                                  setPanel([section.id]);
                                }}
                              >
                                <Icon name={section.icon} />
                                <span>{text}</span>
                                <MenuCountBadge count={total.count} tone={total.tone} />
                                <ChevronRight aria-hidden="true" className="ml-1 group-data-[collapsible=icon]:hidden" />
                              </SidebarMenuButton>
                            </SidebarMenuItem>
                          );
                        })}
                      </SidebarMenu>
                    )}
                  </SidebarGroupContent>
                </SidebarGroup>
              </>
            )
          }
        </SidebarMenuSlider>
      </SidebarContent>
      <SidebarFooter className="border-t p-3">
        <div className="flex items-center gap-2 px-1 py-1 text-[11px] text-muted-foreground">
          <ShieldCheck className="size-4 shrink-0" />
          <span className="group-data-[collapsible=icon]:hidden">{t("admin.restricted")}</span>
        </div>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton tooltip={t("common.signOut")} onClick={onSignOut} disabled={signingOut} className="border">
              {signingOut ? <Spinner /> : <LogOut />}
              <span>{signingOut ? t("common.signingOut") : t("common.signOut")}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}

/**
 * Admin console shell. The sidebar is built at runtime from the backend registry
 * (GET /api/admin/console/menu): only active plugins, only items this admin may open.
 */
export function AdminShell({ brandName, workspace, children }: { brandName: string; workspace: NavGroup[]; children: React.ReactNode }) {
  const t = useT();
  const router = useRouter();
  const path = usePathname();
  const [authenticated, setAuthenticated] = useState<boolean>();
  const [sections, setSections] = useState<ConsoleSection[]>();
  const [menuError, setMenuError] = useState<SafeError>();
  const [menuAttempt, setMenuAttempt] = useState(0);
  const [signingOut, setSigningOut] = useState(false);
  const signIn = adminHref(SIGN_IN_ROUTE);

  useEffect(() => {
    const controller = new AbortController();
    fetchAdminStatus(controller.signal)
      .then((status) => {
        if (!status.authenticated) router.replace(`${signIn}?redirect=${encodeURIComponent(window.location.pathname)}`);
        setAuthenticated(status.authenticated);
      })
      .catch(() => {
        // Status unknown (backend down): show the console; each read reports its own error.
        if (!controller.signal.aborted) setAuthenticated(true);
      });
    return () => controller.abort();
  }, [router, signIn]);

  useEffect(() => {
    if (!authenticated) return;
    const controller = new AbortController();
    fetchConsoleMenu(controller.signal)
      .then((value) => {
        setSections(value);
        setMenuError(undefined);
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        const detail = toSafeError(error);
        if (detail.status === 401) router.replace(signIn);
        setMenuError(detail);
      });
    return () => controller.abort();
  }, [authenticated, menuAttempt, router, signIn]);

  const trail = useMemo<Crumb[]>(() => {
    const root: Crumb = { label: t("admin.consoleName"), href: adminHref("/admin") };
    const found = sections ? findTrail(sections, path) : null;
    if (!found) {
      const page = workspace.flatMap((group) => group.items).find((item) => adminHref(item.href) === path);
      return page ? [root, { label: t(page.labelKey) }] : [root];
    }
    return [root, { label: t.dynamic(found.section.label, found.section.label_default) }, ...found.items.map((item) => ({ label: t.dynamic(item.label, item.label_default) }))];
  }, [sections, path, workspace, t]);

  async function signOut() {
    setSigningOut(true);
    try {
      await adminLogout();
      toast.success(t("common.signedOut"));
      router.replace(signIn);
      router.refresh();
    } catch {
      toast.error(t("common.signOutFailed"));
    } finally {
      setSigningOut(false);
    }
  }

  if (!authenticated) {
    return (
      <main aria-busy="true" className="flex min-h-dvh items-center justify-center">
        <Spinner className="size-6" aria-label={t("common.loading")} />
      </main>
    );
  }

  return (
    <ConsoleMenuContext.Provider value={sections}>
    <SidebarProvider>
      <SkipToContent />
      <AdminSidebar
        brandName={brandName}
        workspace={workspace}
        sections={sections}
        menuError={menuError}
        retryMenu={() => setMenuAttempt((value) => value + 1)}
        path={path}
        signingOut={signingOut}
        onSignOut={() => void signOut()}
      />
      <SidebarInset className="workspace-surface">
        <WorkspaceHeader trail={trail} />
        <div id="content" className="mx-auto flex w-full max-w-[1600px] min-w-0 flex-1 flex-col gap-4 px-3 py-4 sm:px-5 lg:px-6">
          {children}
        </div>
      </SidebarInset>
    </SidebarProvider>
    </ConsoleMenuContext.Provider>
  );
}

/** Title for a registry route that has no web screen yet (used by the admin catch-all page). */
export function useRegistryLabel(path: string) {
  const t = useT();
  const sections = useContext(ConsoleMenuContext);
  const item = sections ? findTrail(sections, path)?.items.at(-1) : undefined;
  return item ? t.dynamic(item.label, item.label_default) : undefined;
}
