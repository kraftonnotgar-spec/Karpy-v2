import type { Metadata } from "next";
import { Suspense } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AdminSignIn } from "@/core/admin/admin-sign-in";
import { Brand } from "@/core/components/brand-mark";
import { brand, t } from "@/products";

export const metadata: Metadata = { title: t("admin.signIn.title"), robots: { index: false, follow: false } };

export default function AdminSignInPage() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 px-4 py-10">
      <Brand name={brand.name} suffix={t("admin.consoleName")} />
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>
            <h1 className="text-base font-semibold">{t("admin.signIn.title")}</h1>
          </CardTitle>
          <CardDescription>{t("admin.signIn.description", { app: brand.name })}</CardDescription>
        </CardHeader>
        <CardContent>
          <Suspense>
            <AdminSignIn />
          </Suspense>
        </CardContent>
      </Card>
    </main>
  );
}
