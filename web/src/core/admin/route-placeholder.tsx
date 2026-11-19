"use client";

import { usePathname } from "next/navigation";
import { PageHeader } from "@/core/components/page-header";
import { EmptyState } from "@/core/components/states";
import { useT } from "@/core/i18n/provider";
import { useRegistryLabel } from "./admin-shell";

/** A menu route registered by a plugin whose web screen is not built yet. */
export function AdminRoutePlaceholder() {
  const t = useT();
  const path = usePathname();
  const label = useRegistryLabel(path) ?? t("admin.consoleName");
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={label} />
      <div className="rounded-lg border">
        <EmptyState icon="inbox" title={t("admin.pageNotBuilt.title", { label })} description={t("admin.pageNotBuilt.description")} className="min-h-80" />
      </div>
    </div>
  );
}
