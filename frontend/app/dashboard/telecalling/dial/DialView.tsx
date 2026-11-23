"use client";
import { RefreshCw } from "lucide-react";
import { useAuthRole } from "../../contexts/AuthRoleContext";
import CockpitModals from "../components/CockpitModals";
import ManualDialPanel from "../components/ManualDialPanel";
import { resolveTelecallingAccess } from "../lib/telecalling-access";
import { useCallingCockpit } from "../lib/useCallingCockpit";

interface DialViewProps {
  initialRole: "owner" | "caller" | null;
  initialCallerId: string | null;
  initialPermissions: string[];
}

const noopRefresh = () => {};

/** The numpad on its own page. Hosts the same cockpit the Dialer uses so dialing, the
 *  accidental-dial countdown, SIM handoff and the wrap-up modal behave identically. */
function DialCockpit({ callerId, blockingWrapups, readOnly }: { callerId: string | null; blockingWrapups: boolean; readOnly: boolean }) {
  const cockpit = useCallingCockpit({ callerId, blockingWrapups, refreshQueue: noopRefresh });

  return (
    <div className="mx-auto w-full max-w-md">
      <div className="rounded-3xl border border-[#e2e8f0] bg-[#f8fafc] p-4 shadow-sm sm:p-5">
        <h2 className="font-display text-xl font-extrabold tracking-tight text-[#0A1528]">Dial a number</h2>
        <p className="mt-0.5 font-label text-xs text-[#475569]">
          Call any number, even one that is not a lead yet. Type a name to find a customer.
        </p>
        {readOnly && (
          <p className="mt-3 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 font-body text-xs text-[#475569]">
            You can view this page but your role cannot place calls.
          </p>
        )}
        <ManualDialPanel cockpit={cockpit} readOnly={readOnly} />
      </div>
      <CockpitModals cockpit={cockpit} />
    </div>
  );
}

export function DialView({ initialRole, initialCallerId, initialPermissions }: DialViewProps) {
  const ctx = useAuthRole();
  // Same resolution as TelecallingView: server seed until the client context settles.
  const role = ctx.loading ? initialRole : ctx.role;
  const callerId = ctx.loading ? initialCallerId : ctx.callerId;
  const permissions = ctx.loading ? initialPermissions : ctx.permissions;
  const { canDial, canViewTelecalling } = resolveTelecallingAccess(role, permissions);

  if (role === null) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <RefreshCw size={24} className="animate-spin text-primary" />
      </div>
    );
  }

  // Telecaller: dials as themselves, blocked by the pending wrap-up gate (as in CallerView).
  if (role === "caller" && callerId) {
    return <DialCockpit callerId={callerId} blockingWrapups readOnly={!canDial} />;
  }

  if (!canViewTelecalling) {
    return (
      <div className="flex min-h-[400px] items-center justify-center rounded-3xl border border-[#e2e8f0] bg-[#f8fafc] p-8 text-center">
        <p className="font-body text-sm text-[#475569]">This section is not available for this role.</p>
      </div>
    );
  }

  // Owner / manager: dials as themselves (AdminView's default "Admin (me)"), no blocking gate.
  return <DialCockpit callerId={null} blockingWrapups={false} readOnly={!canDial} />;
}
