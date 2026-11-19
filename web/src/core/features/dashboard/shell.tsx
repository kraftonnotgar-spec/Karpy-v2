"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";
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
import { ErrorState } from "@/core/components/states";
import { SkipToContent, WorkspaceHeader } from "@/core/components/workspace-header";
import { isActivePath, type NavGroup } from "@/core/features/navigation";
import { useT } from "@/core/i18n/provider";
import { api, postJSON, toSafeError, userAuthAPI, type SafeError } from "@/core/lib/api";
import { toast } from "@/core/lib/notify";

const SIGN_IN = "/sign-in";

function DashboardSidebar({ brandName, nav, path, signingOut, onSignOut }: { brandName: string; nav: NavGroup[]; path: string; signingOut: boolean; onSignOut: () => void }) {
  const t = useT();
  const { isMobile, setOpenMobile } = useSidebar();
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="h-14 justify-center border-b px-4">
        <Link href="/dashboard" className="flex items-center gap-2.5">
          <BrandMark name={brandName} className="hidden group-data-[collapsible=icon]:grid" />
          <Brand name={brandName} className="group-data-[collapsible=icon]:hidden" />
        </Link>
      </SidebarHeader>
      <SidebarContent className="py-2">
        {nav.map((group) => (
          <SidebarGroup key={group.id} className="px-2 py-1">
            {group.labelKey && <SidebarGroupLabel className="h-9 px-2 text-[11px] font-medium text-muted-foreground">{t(group.labelKey)}</SidebarGroupLabel>}
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => {
                  const active = isActivePath(path, item);
                  const label = t(item.labelKey);
                  return (
                    <SidebarMenuItem key={item.id}>
                      <SidebarMenuButton className="h-9 gap-2 px-2 py-1" asChild isActive={active} tooltip={label}>
                        <Link href={item.href} aria-current={active ? "page" : undefined} onClick={() => isMobile && setOpenMobile(false)}>
                          <Icon name={item.icon} />
                          <span>{label}</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter className="border-t">
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

/** Signed-in user workspace: checks the session, then renders sidebar + header + content. */
export function DashboardShell({ brandName, nav, children }: { brandName: string; nav: NavGroup[]; children: React.ReactNode }) {
  const t = useT();
  const router = useRouter();
  const path = usePathname();
  const [state, setState] = useState<{ ready: boolean; error?: SafeError }>({ ready: false });
  const [attempt, setAttempt] = useState(0);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api(`${userAuthAPI}/me`, undefined, { signal: controller.signal }, { refreshOn401: true })
      .then(() => setState({ ready: true }))
      .catch((error) => {
        if (controller.signal.aborted) return;
        const detail = toSafeError(error);
        if (detail.status === 401) router.replace(`${SIGN_IN}?redirect=${encodeURIComponent(window.location.pathname)}`);
        setState({ ready: false, error: detail });
      });
    return () => controller.abort();
  }, [router, attempt]);

  async function signOut() {
    setSigningOut(true);
    try {
      await postJSON(`${userAuthAPI}/logout`, {});
      toast.success(t("common.signedOut"));
      router.replace(SIGN_IN);
      router.refresh();
    } catch {
      toast.error(t("common.signOutFailed"));
    } finally {
      setSigningOut(false);
    }
  }

  if (!state.ready && (!state.error || state.error.status === 401)) {
    return (
      <main aria-busy="true" className="flex min-h-dvh items-center justify-center">
        <Spinner className="size-6" aria-label={t("common.loading")} />
      </main>
    );
  }

  const current = nav.flatMap((group) => group.items).find((item) => isActivePath(path, item));
  return (
    <SidebarProvider>
      <SkipToContent />
      <DashboardSidebar brandName={brandName} nav={nav} path={path} signingOut={signingOut} onSignOut={() => void signOut()} />
      <SidebarInset className="workspace-surface">
        <WorkspaceHeader trail={[{ label: current ? t(current.labelKey) : brandName }]} />
        <div id="content" className="mx-auto flex w-full max-w-[1600px] min-w-0 flex-1 flex-col gap-4 px-3 py-4 sm:px-5 lg:px-6">
          {state.error ? (
            <div className="rounded-lg border">
              <ErrorState error={state.error} retry={() => setAttempt((value) => value + 1)} signInHref={SIGN_IN} className="min-h-80" />
            </div>
          ) : (
            children
          )}
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
