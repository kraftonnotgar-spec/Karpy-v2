import type { Metadata, Viewport } from "next";
import Script from "next/script";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeSync } from "@/core/components/preferences";
import { themeScript } from "@/core/components/theme-script";
import { I18nProvider } from "@/core/i18n/provider";
import { brand, locale, messages, product, t } from "@/products";
import "./globals.css";

const tagline = brand.tagline ?? t("brand.tagline");

export const metadata: Metadata = {
  title: { default: brand.name, template: t("meta.titleTemplate", { app: brand.name }) },
  description: t("meta.description", { app: brand.name, tagline }),
  applicationName: brand.name,
  appleWebApp: { capable: true, title: brand.shortName, statusBarStyle: "default" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // The pre-paint theme script sets the class before hydration; data-product scopes the theme tokens.
    <html lang={locale} data-product={product.key} className="h-full antialiased" suppressHydrationWarning>
      <body className="min-h-full">
        <Script id="theme-init" strategy="beforeInteractive">
          {themeScript}
        </Script>
        <ThemeSync />
        <I18nProvider locale={locale} messages={messages}>
          <TooltipProvider>
            {children}
            <Toaster />
          </TooltipProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
