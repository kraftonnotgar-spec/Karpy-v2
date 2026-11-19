import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Brand } from "@/core/components/brand-mark";
import { SignInForm } from "@/core/features/auth/sign-in-form";
import { brand, t } from "@/products";

export const metadata: Metadata = { title: t("auth.signIn.title") };

export default function SignInPage() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 px-4 py-10">
      <Link href="/" aria-label={t("auth.signIn.backHome")}>
        <Brand name={brand.name} />
      </Link>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>
            <h1 className="text-base font-semibold">{t("auth.signIn.title")}</h1>
          </CardTitle>
          <CardDescription>{t("auth.signIn.description", { app: brand.name })}</CardDescription>
        </CardHeader>
        <CardContent>
          <Suspense>
            <SignInForm />
          </Suspense>
        </CardContent>
      </Card>
    </main>
  );
}
