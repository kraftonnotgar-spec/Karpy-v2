/** Page heading with optional actions on the right. Text comes from the caller (catalogs). */
export function PageHeader({
  title,
  description,
  children,
  compactActions = false,
}: {
  title: string;
  description?: string;
  children?: React.ReactNode;
  compactActions?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
      <div className="flex min-w-0 flex-col gap-0.5">
        <h1 className="text-[15px] leading-6 font-normal sm:text-base">{title}</h1>
        {description && <p className="text-[13px] text-muted-foreground">{description}</p>}
      </div>
      {children && (
        <div
          data-page-actions
          data-compact-toolbar={compactActions || undefined}
          className={compactActions ? "ml-auto flex shrink-0 items-center gap-1" : "ml-auto flex min-w-0 max-w-full flex-wrap items-center justify-end gap-1.5"}
        >
          {children}
        </div>
      )}
    </div>
  );
}
