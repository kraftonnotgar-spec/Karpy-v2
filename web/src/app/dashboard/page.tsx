import type { Metadata } from "next";
import { PageHeader } from "@/core/components/page-header";
import { EmptyPanel } from "@/core/components/empty-panel";
import { t } from "@/products";

export const metadata: Metadata = { title: t("dashboard.overview.title") };

export default function DashboardOverview() {
  return (
    <>
      <PageHeader title={t("dashboard.overview.title")} description={t("dashboard.overview.description")} />
      <EmptyPanel title={t("dashboard.overview.emptyTitle")} description={t("dashboard.overview.emptyDescription")} />
    </>
  );
}
