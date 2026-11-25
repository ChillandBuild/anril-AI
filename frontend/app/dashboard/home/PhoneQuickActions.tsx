"use client";
import Link from "next/link";
import { Receipt, Send, SquarePen, type LucideIcon } from "lucide-react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { quickActionsFor, type QuickAction } from "./quickActions";

const ICONS: Record<QuickAction["id"], LucideIcon> = {
  "new-bill": Receipt,
  "new-template": SquarePen,
  broadcast: Send,
};

/** Phone-only shortcuts under Home's top: the daily jobs one tap away instead of three. */
export function PhoneQuickActions() {
  const { role, permissions, enabledFeatures, loading } = useAuthRole();
  if (loading) return null;
  const actions = quickActionsFor({ role, permissions, enabledFeatures });
  if (actions.length === 0) return null;
  return (
    <nav aria-label="Quick actions" className="-mx-3 flex gap-2 overflow-x-auto px-3 sm:-mx-4 sm:px-4 lg:hidden">
      {actions.map((a) => {
        const Icon = ICONS[a.id];
        return (
          <Link
            key={a.id}
            href={a.href}
            className="flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-border bg-white px-3.5 font-label text-[13px] font-bold text-ink active:bg-surface-mid"
          >
            <Icon size={15} aria-hidden className="text-primary-900" />
            {a.label}
          </Link>
        );
      })}
    </nav>
  );
}
