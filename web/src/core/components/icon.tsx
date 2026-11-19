"use client";

import {
  ArrowLeftRight,
  BarChart3,
  Bell,
  Box,
  Building2,
  Circle,
  CreditCard,
  FileText,
  Folder,
  Globe,
  Image as ImageIcon,
  Inbox,
  KeyRound,
  LayoutDashboard,
  LayoutGrid,
  Library,
  LifeBuoy,
  ListTodo,
  Mail,
  Puzzle,
  Settings,
  Shield,
  ShoppingCart,
  Smile,
  Store,
  Tag,
  Users,
  type LucideIcon,
  type LucideProps,
} from "lucide-react";
import { DynamicIcon, iconNames } from "lucide-react/dynamic";

/**
 * Lucide icon by kebab-case name, as menus and the backend registry send it ("inbox",
 * "layout-dashboard"). Common names render instantly from this map; any other valid lucide
 * name loads on demand; unknown names fall back to a neutral circle.
 */
const common: Record<string, LucideIcon> = {
  "arrow-left-right": ArrowLeftRight,
  "bar-chart-3": BarChart3,
  bell: Bell,
  box: Box,
  "building-2": Building2,
  circle: Circle,
  "credit-card": CreditCard,
  "file-text": FileText,
  folder: Folder,
  globe: Globe,
  image: ImageIcon,
  inbox: Inbox,
  "key-round": KeyRound,
  "layout-dashboard": LayoutDashboard,
  "layout-grid": LayoutGrid,
  library: Library,
  "life-buoy": LifeBuoy,
  "list-todo": ListTodo,
  mail: Mail,
  puzzle: Puzzle,
  settings: Settings,
  shield: Shield,
  "shopping-cart": ShoppingCart,
  smile: Smile,
  store: Store,
  tag: Tag,
  users: Users,
};
const known = new Set<string>(iconNames);

export const FallbackIcon = Circle;

export function Icon({ name, ...props }: { name?: string | null } & Omit<LucideProps, "name">) {
  const key = (name ?? "").trim().toLowerCase();
  const Static = common[key];
  if (Static) return <Static aria-hidden="true" {...props} />;
  if (key && known.has(key)) {
    return <DynamicIcon name={key as (typeof iconNames)[number]} aria-hidden="true" fallback={() => <FallbackIcon aria-hidden="true" {...props} />} {...props} />;
  }
  return <FallbackIcon aria-hidden="true" {...props} />;
}
