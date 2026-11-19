import { cn } from "@/lib/utils";

/**
 * Text-only brand lockup until a product supplies logo files: the first letter of the brand
 * name in a token-coloured square, plus the name.
 */
export function BrandMark({ name, className }: { name: string; className?: string }) {
  return (
    <span aria-hidden="true" className={cn("grid size-8 shrink-0 place-items-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground", className)}>
      {name.slice(0, 1).toUpperCase()}
    </span>
  );
}

export function Brand({ name, suffix, className }: { name: string; suffix?: string; className?: string }) {
  return (
    <span className={cn("flex min-w-0 items-center gap-2.5", className)}>
      <BrandMark name={name} />
      <span className="min-w-0 truncate font-heading text-[15px] font-semibold">{name}</span>
      {suffix && <span className="shrink-0 rounded-md border px-1.5 py-0.5 text-[11px] text-muted-foreground">{suffix}</span>}
    </span>
  );
}
