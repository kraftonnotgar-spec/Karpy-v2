"use client";

import { toast as sonner, type ExternalToast } from "sonner";

// Stable IDs collapse repeated outcomes without including copied values or secrets.
function message(type: "success" | "error" | "warning" | "info", text: string, options?: ExternalToast) {
  return sonner[type](text, { id: `${type}:${text}`, ...options });
}

export const toast = {
  success: (text: string, options?: ExternalToast) => message("success", text, options),
  error: (text: string, options?: ExternalToast) => message("error", text, options),
  warning: (text: string, options?: ExternalToast) => message("warning", text, options),
  info: (text: string, options?: ExternalToast) => message("info", text, options),
  dismiss: sonner.dismiss,
};
