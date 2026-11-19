import type { Metadata } from "next";
import { AdminShell } from "@/core/admin/admin-shell";
import { adminWorkspaceNav, brand, t } from "@/products";

export const metadata: Metadata = { title: t("admin.consoleName"), robots: { index: false, follow: false } };

export default function AdminConsoleLayout({ children }: LayoutProps<"/admin">) {
  return (
    <AdminShell brandName={brand.name} workspace={adminWorkspaceNav}>
      {children}
    </AdminShell>
  );
}
