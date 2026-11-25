export interface QuickActionsInput {
  role: "owner" | "caller" | null;
  permissions: string[];
  enabledFeatures: string[];
}

export interface QuickAction {
  id: "new-bill" | "new-template" | "broadcast";
  label: string;
  href: string;
}

/**
 * The phone Home shortcuts this person may use. Same rules as the header's New bill button and the
 * More menu's Templates and Reach rows, plus the manage permission (a shortcut creates something).
 */
export function quickActionsFor({ role, permissions, enabledFeatures }: QuickActionsInput): QuickAction[] {
  const can = (permission: string) => role === "owner" || permissions.includes(permission);
  const outboundOn = enabledFeatures.includes("outbound_messaging");
  const out: QuickAction[] = [];
  if (can("deals.manage")) out.push({ id: "new-bill", label: "New bill", href: "/dashboard/deals/new-bill" });
  if (outboundOn && can("templates.manage")) out.push({ id: "new-template", label: "New template", href: "/dashboard/templates/new" });
  if (outboundOn && can("outbound_leads.manage")) out.push({ id: "broadcast", label: "Broadcast", href: "/dashboard/outbound-leads" });
  return out;
}
