import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Brand } from "@/core/components/brand-mark";
import { brand, t } from "@/products";

/** Neutral landing page: brand, one headline, the two ways in. */
export default function Home() {
  const year = Number(process.env.NEXT_PUBLIC_BUILD_YEAR) || new Date().getUTCFullYear();
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-4 py-5">
        <Brand name={brand.name} />
        <Button asChild variant="outline">
          <Link href="/sign-in">{t("site.ctaSignIn")}</Link>
        </Button>
      </header>
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center gap-5 px-4 py-16">
        <p className="text-[13px] font-medium text-primary">{t("site.eyebrow")}</p>
        <h1 className="max-w-2xl font-heading text-3xl leading-tight font-semibold sm:text-4xl">{t("site.headline")}</h1>
        <p className="max-w-xl text-muted-foreground">{brand.tagline ?? t("brand.tagline")}</p>
        <p className="max-w-xl text-[15px] text-muted-foreground">{t("site.body")}</p>
        <div className="flex flex-wrap gap-2 pt-2">
          <Button asChild className="h-10 px-4">
            <Link href="/dashboard">{t("site.ctaDashboard")}</Link>
          </Button>
          <Button asChild variant="outline" className="h-10 px-4">
            <Link href="/sign-in">{t("site.ctaSignIn")}</Link>
          </Button>
        </div>
      </main>
      <footer className="mx-auto flex w-full max-w-5xl flex-wrap justify-between gap-2 border-t px-4 py-6 text-[12px] text-muted-foreground">
        <span>{t("common.copyright", { year, app: brand.name })}</span>
        {brand.supportEmail && <a href={`mailto:${brand.supportEmail}`} className="hover:text-foreground">{t("site.support", { email: brand.supportEmail })}</a>}
      </footer>
    </div>
  );
}
