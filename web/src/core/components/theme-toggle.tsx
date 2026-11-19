"use client";

import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useT } from "@/core/i18n/provider";
import { useTheme } from "./preferences";

export function ThemeToggle() {
  const t = useT();
  const { resolved, setTheme, canToggle } = useTheme();
  if (!canToggle) return null;
  const label = resolved === "dark" ? t("theme.toLight") : t("theme.toDark");
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="outline" size="icon" aria-label={label} onClick={() => setTheme(resolved === "dark" ? "light" : "dark")}>
          {resolved === "dark" ? <Moon /> : <Sun />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
