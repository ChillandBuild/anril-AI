"use client";

import { Phone } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { dueText, type LiveCallback, type LiveWaitingLead } from "@/lib/callIqApi";
import { useActiveCall } from "@/app/dashboard/contexts/ActiveCallContext";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { isMobileDialSurface, openNativeDialer } from "@/app/dashboard/telecalling/lib/sim-dialer";
import { Card } from "./CallIqShell";

interface Target {
  leadId: string;
  name: string | null;
  phone: string;
  callbackJobId?: string;
}

/** Start a call from a Live row. The server refuses Do Not Call and Said stop customers. */
function useDial() {
  const { setActiveCall } = useActiveCall();
  const { callerId } = useAuthRole();
  return async (t: Target) => {
    if (!callerId) {
      toast.error("You need a telecaller profile to place a call.");
      return;
    }
    try {
      const res = await api.calls.initiate({ leadId: t.leadId, callbackJobId: t.callbackJobId }, callerId);
      setActiveCall({ leadId: res.lead_id ?? t.leadId, name: res.lead_name ?? t.name, phone: t.phone, callLogId: res.call_log_id ?? null });
      if (res.provider === "sim_basic") {
        if (!isMobileDialSurface() || !openNativeDialer(t.phone)) toast.error("Open this page on the phone to dial from your SIM.");
        else toast.success(`Opening phone dialer for ${t.name || t.phone}...`);
      } else {
        toast.success(`Calling ${t.name || t.phone}...`);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Call failed");
    }
  };
}

function CallButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-lg bg-emerald-600 px-3 font-label text-sm font-bold text-white hover:bg-emerald-700">
      <Phone size={14} aria-hidden /> Call
    </button>
  );
}

function Row({ title, sub, action }: { title: string; sub: string; action: React.ReactNode }) {
  return (
    <li className="flex items-center justify-between gap-3 py-2">
      <div className="min-w-0">
        <p className="truncate font-label text-sm font-bold text-primary">{title}</p>
        <p className="truncate font-label text-xs text-ink-secondary">{sub}</p>
      </div>
      {action}
    </li>
  );
}

export function CallbacksDue({ rows, now }: { rows: LiveCallback[]; now: Date }) {
  const dial = useDial();
  return (
    <Card>
      <h2 className="font-display text-base font-bold text-primary">Callbacks due now</h2>
      {rows.length === 0 ? (
        <p className="mt-2 font-label text-sm text-ink-secondary">Nothing due in the last 30 minutes or the next 15.</p>
      ) : (
        <ul className="mt-2 divide-y divide-black/5">
          {rows.map((r) => (
            <Row
              key={r.job_id}
              title={`${r.name || "Unnamed"} · ${r.phone}`}
              sub={[dueText(r.due_at, now), r.caller_name, r.why].filter(Boolean).join(" · ")}
              action={<CallButton onClick={() => dial({ leadId: r.lead_id, name: r.name, phone: r.phone, callbackJobId: r.job_id })} />}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}

export function WaitingHotLeads({ total, rows }: { total: number; rows: LiveWaitingLead[] }) {
  const dial = useDial();
  return (
    <Card>
      <h2 className="font-display text-base font-bold text-primary">
        Waiting <span className="font-label text-xs font-bold text-ink-secondary">Hot leads not called yet today ({total})</span>
      </h2>
      {rows.length === 0 ? (
        <p className="mt-2 font-label text-sm text-ink-secondary">Every Hot lead has been called today.</p>
      ) : (
        <ul className="mt-2 divide-y divide-black/5">
          {rows.map((r) => (
            <Row
              key={r.lead_id}
              title={`${r.name || "Unnamed"} · ${r.phone}`}
              sub={r.caller_name ? `With ${r.caller_name}` : ""}
              action={<CallButton onClick={() => dial({ leadId: r.lead_id, name: r.name, phone: r.phone })} />}
            />
          ))}
          {total > rows.length && <li className="py-2 font-label text-xs text-ink-secondary">Showing the first {rows.length} of {total}.</li>}
        </ul>
      )}
    </Card>
  );
}
