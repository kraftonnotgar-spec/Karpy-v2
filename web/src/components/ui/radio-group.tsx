"use client";
import { RadioGroup as RadioPrimitive } from "radix-ui";
import { Circle } from "lucide-react";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export function RadioGroup({
  className,
  ...props
}: ComponentProps<typeof RadioPrimitive.Root>) {
  return (
    <RadioPrimitive.Root
      data-slot="radio-group"
      className={cn("grid gap-2", className)}
      {...props}
    />
  );
}
export function RadioGroupItem({
  className,
  ...props
}: ComponentProps<typeof RadioPrimitive.Item>) {
  return (
    <RadioPrimitive.Item
      data-slot="radio-group-item"
      className={cn(
        "grid size-4 shrink-0 place-items-center rounded-full border border-input outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 data-[state=checked]:border-primary data-[state=checked]:text-primary",
        className,
      )}
      {...props}
    >
      <RadioPrimitive.Indicator>
        <Circle className="size-2 fill-current" />
      </RadioPrimitive.Indicator>
    </RadioPrimitive.Item>
  );
}
