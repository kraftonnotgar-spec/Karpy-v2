"use client";

import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useT } from "@/core/i18n/provider";
import { COPY_FEEDBACK_MS, copyText } from "@/core/lib/clipboard";
import { toast } from "@/core/lib/notify";
import { cn } from "@/lib/utils";

/** Copy -> Check swap; both icons stay mounted so the button never changes size. */
export function CopyIcon({ copied, plain = false }: { copied: boolean; /** Inherit text colour (on primary buttons). */ plain?: boolean }) {
  return (
    <span aria-hidden="true" data-copied={copied || undefined} className="relative inline-flex size-4 shrink-0">
      <Copy className={cn("absolute inset-0 transition-[opacity,transform] duration-200 motion-reduce:transition-none", copied ? "scale-50 opacity-0" : "scale-100 opacity-100")} />
      <Check className={cn("absolute inset-0 transition-[opacity,transform] duration-200 motion-reduce:transition-none", !plain && "text-primary", copied ? "scale-100 opacity-100" : "scale-50 opacity-0")} />
    </span>
  );
}

/** Shared copy state: reliable copy, short confirmation, toast on failure. */
export function useCopy(onResult?: (copied: boolean) => void, success?: string) {
  const t = useT();
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), COPY_FEEDBACK_MS);
    return () => clearTimeout(timer);
  }, [state]);
  async function copy(value: string) {
    const copied = await copyText(value);
    setState(copied ? "copied" : "failed");
    if (copied) toast.success(success ?? t("copy.copiedToast"));
    else toast.error(t("copy.failedToast"));
    onResult?.(copied);
    return copied;
  }
  return { state, copy };
}

export function CopyButton({
  value,
  label,
  onResult,
  variant = "ghost",
  children,
  disabled,
  className,
  success,
}: {
  value: string;
  label?: string;
  onResult?: (copied: boolean) => void;
  /** "outline" matches square icon buttons beside inputs; "default" is the primary action. */
  variant?: "ghost" | "outline" | "default";
  /** Visible text turns the icon button into a labelled button. */
  children?: React.ReactNode;
  disabled?: boolean;
  className?: string;
  /** Toast text on success. */
  success?: string;
}) {
  const t = useT();
  const { state, copy } = useCopy(onResult, success);
  const [hover, setHover] = useState(false);
  const idleLabel = label ?? t("copy.label");
  const text = state === "copied" ? t("copy.copied") : state === "failed" ? t("copy.failed") : idleLabel;
  return (
    // The tooltip stays open while the confirmation shows, including after keyboard use.
    <Tooltip open={!disabled && (hover || state !== "idle")} onOpenChange={setHover}>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant={variant}
          size={children ? "default" : variant === "ghost" ? "icon-sm" : "icon"}
          aria-label={children ? undefined : idleLabel}
          disabled={disabled || !value}
          data-copy-state={state}
          onClick={(event) => {
            // Rows can be clickable; copying must not also open the record.
            event.stopPropagation();
            void copy(value);
          }}
          className={cn(!children && (variant === "ghost" ? "text-muted-foreground" : variant === "outline" ? "text-foreground" : undefined), className)}
        >
          <CopyIcon copied={state === "copied"} plain={variant === "default"} />
          {children && <span>{state === "copied" ? t("copy.copied") : children}</span>}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
      <span role="status" aria-live="polite" className="sr-only">
        {state === "idle" ? "" : text}
      </span>
    </Tooltip>
  );
}
