import { PageHeader } from "@/core/components/page-header";
import { EmptyPanel } from "@/core/components/empty-panel";
import { t } from "@/products";

/** Placeholder for menu entries whose screens a product has not built yet. */
export default function DashboardPlaceholder() {
  return (
    <>
      <PageHeader title={t("dashboard.overview.emptyTitle")} />
      <EmptyPanel title={t("dashboard.overview.emptyTitle")} description={t("dashboard.overview.emptyDescription")} />
    </>
  );
}
