"use client";

import { useCallback, useState, type ReactNode } from "react";
import { Command } from "cmdk";
import { Check, ChevronsUpDown, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

type Option = { value: string; label: string; detail?: string; icon?: ReactNode };

/** Searchable shadcn Popover/Command composition for the dashboard's Radix stack. */
export function Combobox({ value, onValueChange, onBlur, options, label, searchPlaceholder, trigger, className }: {
  value: string; onValueChange: (value: string) => void; onBlur?: () => void;
  options: readonly Option[]; label: string; searchPlaceholder: string; trigger: ReactNode; className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [listId, setListId] = useState<string>();
  const listRef = useCallback((node: HTMLDivElement | null) => setListId(node?.id), []);
  return <Popover open={open} onOpenChange={next => { setOpen(next); if (!next) onBlur?.(); }}>
    <PopoverTrigger asChild>
      <Button type="button" variant="outline" role="combobox" aria-label={`${label}: ${options.find(option => option.value === value)?.label ?? value}`} aria-expanded={open}
        aria-controls={open ? listId : undefined} aria-haspopup="listbox" data-slot="combobox-trigger"
        className={cn("h-10 shrink-0 justify-between gap-2 px-3 font-normal", className)}>
        {trigger}<ChevronsUpDown className="size-3.5 text-muted-foreground" />
      </Button>
    </PopoverTrigger>
    <PopoverContent align="start" className="app-combobox w-[300px] gap-0 p-1.5" onCloseAutoFocus={() => onBlur?.()}>
      <Command label={searchPlaceholder}>
        <div className="flex h-10 items-center gap-2 rounded-md border bg-muted/30 px-3">
          <Search className="size-4 shrink-0 text-muted-foreground" />
          <Command.Input aria-label={searchPlaceholder} placeholder={searchPlaceholder}
            className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground" />
        </div>
        <Command.List ref={listRef} className="max-h-56 overflow-y-auto overscroll-contain pt-1">
          <Command.Empty className="px-3 py-4 text-[13px] text-muted-foreground">No matches found.</Command.Empty>
          {options.map(option => <Command.Item key={option.value} value={option.value} keywords={[option.label, option.detail ?? ""]}
            onSelect={() => { onValueChange(option.value); setOpen(false); onBlur?.(); }}
            className="flex min-h-10 cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-[13px] font-normal outline-none data-[selected=true]:bg-accent">
            {option.icon}<span className="min-w-0 flex-1">{option.label}</span>
            {option.detail && <span className="text-muted-foreground">{option.detail}</span>}
            {value === option.value && <Check className="size-3.5 shrink-0 text-primary" />}
          </Command.Item>)}
        </Command.List>
      </Command>
    </PopoverContent>
  </Popover>;
}
