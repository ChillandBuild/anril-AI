"use client";
import { RefreshCw } from "lucide-react";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { AdminDashboardData } from "@/hooks/useApi";
import CallerView from "./CallerView";
import AdminView from "./AdminView";
import { resolveTelecallingAccess } from "./lib/telecalling-access";

interface TelecallingViewProps {
  initialRole: "owner" | "caller" | null;
  initialCallerId: string | null;
  initialPermissions: string[];
  fallbackAdminData: AdminDashboardData | null;
}

export function TelecallingView({ initialRole, initialCallerId, initialPermissions, fallbackAdminData }: TelecallingViewProps) {
  const ctx = useAuthRole();
  // Prefer the server-seeded role/callerId until the client context resolves.
  // Both read team/me, so they agree — this just skips the first-paint spinner
  // for BOTH admins (AdminView) and telecallers (CallerView).
  const role = ctx.loading ? initialRole : ctx.role;
  const callerId = ctx.loading ? initialCallerId : ctx.callerId;
  const permissions = ctx.loading ? initialPermissions : ctx.permissions;
  const { canDial, canViewTelecalling } = resolveTelecallingAccess(role, permissions);

  if (role === null) {
    // No server seed and context still resolving (e.g. cold backend) — brief spinner.
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <RefreshCw size={24} className="animate-spin text-primary" />
      </div>
    );
  }

  if (role === "caller" && callerId) {
    return <CallerView callerId={callerId} readOnly={!canDial} />;
  }

  if (!canViewTelecalling) {
    return (
      <div className="flex min-h-[400px] items-center justify-center rounded-3xl border border-[#e2e8f0] bg-[#f8fafc] p-8 text-center">
        <p className="font-body text-sm text-[#475569]">This section is not available for this role.</p>
      </div>
    );
  }

  return <AdminView fallbackData={fallbackAdminData ?? undefined} readOnly={!canDial} />;
}
