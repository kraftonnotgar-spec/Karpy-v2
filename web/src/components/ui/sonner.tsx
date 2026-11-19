"use client";

import { Check, X, Info, TriangleAlert, LoaderCircle } from "lucide-react";
import { Toaster as Sonner, type ToasterProps } from "sonner";
import { useTheme } from "@/core/components/preferences";

export function Toaster(props: ToasterProps) {
  const { resolved } = useTheme();
  return <Sonner {...props} theme={resolved === "dark" ? "dark" : "light"}
    position="top-right" duration={3000} visibleToasts={2} expand gap={8}
    style={{ width: "min(420px, calc(100vw - 24px))" }}
    offset={{ top: 8, right: 12 }} mobileOffset={{ top: 8, left: 12, right: 12 }}
    className="toaster group" toastOptions={{ classNames: {
      toast: "app-toast", title: "app-toast-title", description: "app-toast-description",
    } }}
    icons={{
      success: <span className="app-toast-icon app-toast-success"><Check /></span>,
      error: <span className="app-toast-icon app-toast-error"><X /></span>,
      warning: <span className="app-toast-icon app-toast-warning"><TriangleAlert /></span>,
      info: <span className="app-toast-icon app-toast-info"><Info /></span>,
      loading: <LoaderCircle className="size-5 animate-spin motion-reduce:animate-none" />,
    }} />;
}
