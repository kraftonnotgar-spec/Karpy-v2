import { DashboardShell } from "@/core/features/dashboard/shell";
import { brand, dashboardNav } from "@/products";

export default function DashboardLayout({ children }: LayoutProps<"/dashboard">) {
  return (
    <DashboardShell brandName={brand.name} nav={dashboardNav}>
      {children}
    </DashboardShell>
  );
}
