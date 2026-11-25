"use client";
import { AlertCircle, Copy, Phone, RefreshCw, Send, X } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { toast } from "sonner";
import { formatPhone } from "@/lib/utils";
import { formatIstWhen } from "@/lib/call-wrapup";
import { pendingCallLabel } from "../lib/feedbackLabels";
import type { CallingCockpit } from "../lib/useCallingCockpit";
import WrapupModal from "./wrapup/WrapupModal";

/**
 * Shared overlays for the calling cockpit: accidental-dial guard, SIM desktop handoff, the
 * mandatory two-tap wrap-up and the blocking pending-wrap-ups list. All state comes from
 * useCallingCockpit; the blocking list only renders when `blockingWrapups` is on.
 */
export default function CockpitModals({ cockpit }: { cockpit: CallingCockpit }) {
  const {
    dialCountdown,
    dialTarget,
    cancelDial,
    showWrapupModal,
    activeCallCtx,
    wrapupDraft,
    setWrapupDraft,
    wrapupContext,
    catalogItems,
    wrapupSaving,
    handleWrapupSubmit,
    pendingWrapups,
    openWrapupFromLog,
    blockingWrapups,
    simHandoffLead,
    setSimHandoffLead,
    simHandoffSending,
    sendSimHandoffToMobile,
    activeCallProvider,
    wrapupStartedAt,
    setWrapupStartedAt,
    wrapupEndedAt,
    setWrapupEndedAt,
  } = cockpit;

  const simHandoffUrl = simHandoffLead && typeof window !== "undefined"
    ? `${window.location.origin}/dashboard/telecalling?lead_id=${simHandoffLead.id}`
    : "";

  const copySimNumber = async () => {
    if (!simHandoffLead?.phone) return;
    try {
      await navigator.clipboard.writeText(simHandoffLead.phone);
      toast.success("Phone number copied");
    } catch {
      toast.error("Could not copy phone number");
    }
  };

  return (
    <>
      {/* Accidental-dial guard countdown */}
      {dialCountdown !== null && dialTarget && (
        <div className="fixed inset-0 bg-[#0A1528]/70 backdrop-blur-sm flex items-center justify-center z-[70]">
          <div className="bg-white rounded-3xl p-8 max-w-sm w-full mx-4 shadow-2xl border border-[#e2e8f0] text-center animate-in fade-in zoom-in-95">
            <div className="w-16 h-16 bg-[var(--primary-50)] text-[var(--primary-800)] rounded-full flex items-center justify-center mx-auto mb-4 animate-bounce">
              <Phone size={24} />
            </div>
            <h3 className="font-display text-lg font-bold text-[#13284A]">Calling in {dialCountdown}s...</h3>
            <p className="font-body text-sm text-[#475569] mt-1.5">
              Target: {"lead" in dialTarget ? dialTarget.lead?.name || dialTarget.lead?.phone : dialTarget.phone}
            </p>
            <button
              onClick={cancelDial}
              className="mt-6 w-full py-3 bg-red-50 hover:bg-red-100 text-red-600 font-label text-sm font-bold rounded-2xl transition-all border border-red-200"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* SIM Basic desktop handoff */}
      {simHandoffLead && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[#0A1528]/75 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md overflow-hidden rounded-3xl border border-[#e2e8f0] bg-white shadow-2xl animate-in fade-in zoom-in-95">
            <div className="flex items-start justify-between gap-4 border-b border-[#f1f5f9] px-6 py-5">
              <div>
                <span className="rounded-full bg-primary-light px-3 py-1 font-label text-[10px] font-black uppercase tracking-wider text-primary">
                  Calling from your phone
                </span>
                <h3 className="mt-3 font-display text-xl font-extrabold text-[#0A1528]">Open this lead on mobile</h3>
                <p className="mt-1 font-body text-sm leading-relaxed text-[#475569]">
                  This tenant uses SIM calling. Open this lead on your phone to call using your SIM.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSimHandoffLead(null)}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[#475569] hover:bg-[#f1f5f9] hover:text-[#13284A]"
                aria-label="Close"
              >
                <X size={18} />
              </button>
            </div>

            <div className="space-y-5 px-6 py-5">
              <div className="rounded-2xl border border-[#e2e8f0] bg-[#f8fafc] p-4">
                <p className="font-label text-[10px] font-black uppercase tracking-wider text-[#94a3b8]">Lead</p>
                <p className="mt-1 font-display text-base font-bold text-[#0A1528]">{simHandoffLead.name || "Unnamed Lead"}</p>
                <div className="mt-3 flex items-center justify-between gap-3 rounded-xl bg-white px-3 py-2">
                  <span className="font-mono text-sm font-bold text-[#13284A]">{formatPhone(simHandoffLead.phone)}</span>
                  <button
                    type="button"
                    onClick={copySimNumber}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[#e2e8f0] px-2.5 py-1.5 font-label text-[11px] font-bold text-[#334155] hover:border-primary-muted hover:text-primary"
                  >
                    <Copy size={12} />
                    Copy
                  </button>
                </div>
              </div>

              <div className="flex items-center justify-center rounded-3xl border border-primary-muted bg-primary-light/40 p-5">
                {simHandoffUrl && (
                  <QRCodeSVG
                    value={simHandoffUrl}
                    size={168}
                    bgColor="#ffffff"
                    fgColor="#0A1528"
                    level="M"
                    includeMargin
                    className="rounded-2xl bg-white p-2 shadow-sm"
                  />
                )}
              </div>

              <button
                type="button"
                onClick={sendSimHandoffToMobile}
                disabled={simHandoffSending}
                className="flex w-full items-center justify-center gap-2 rounded-2xl bg-primary px-4 py-3 font-label text-sm font-black text-white shadow-md transition-all hover:bg-primary-dark disabled:opacity-50"
              >
                {simHandoffSending ? <RefreshCw size={15} className="animate-spin" /> : <Send size={15} />}
                Send to my mobile
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Mandatory two-tap wrap-up */}
      {showWrapupModal && activeCallCtx && (
        <WrapupModal
          callee={activeCallCtx.name || formatPhone(activeCallCtx.phone ?? "") || "this lead"}
          provider={activeCallProvider}
          context={wrapupContext}
          draft={wrapupDraft}
          onChange={setWrapupDraft}
          saving={wrapupSaving}
          onSubmit={handleWrapupSubmit}
          catalogItems={catalogItems}
          simTiming={
            activeCallProvider === "sim_basic"
              ? { startedAt: wrapupStartedAt, endedAt: wrapupEndedAt, setStartedAt: setWrapupStartedAt, setEndedAt: setWrapupEndedAt }
              : null
          }
        />
      )}

      {/* Blocking pending-wrap-ups list (telecaller discipline gate only) */}
      {blockingWrapups && pendingWrapups.length > 0 && !showWrapupModal && (
        <div className="fixed inset-0 bg-[#0A1528]/85 backdrop-blur-md flex items-center justify-center z-[70] p-4 animate-in fade-in">
          <div className="bg-white rounded-3xl p-8 max-w-2xl w-full max-h-[80vh] shadow-2xl flex flex-col border border-[#e2e8f0]">
            <div className="text-center mb-6 shrink-0">
              <div className="w-12 h-12 bg-amber-50 border border-amber-200 text-amber-600 rounded-full flex items-center justify-center mx-auto mb-3">
                <AlertCircle size={24} />
              </div>
              <h2 className="font-display text-xl font-extrabold text-[#0A1528]">Action Required: Pending Call Wrap-ups</h2>
              <p className="font-body text-xs text-[#94a3b8] mt-1.5">
                You have {pendingWrapups.length} call(s) that need an outcome. Submit feedback for each to unlock the app.
              </p>
            </div>

            <div className="flex-1 overflow-y-auto space-y-3 mb-2 pr-1">
              {pendingWrapups.map((log) => (
                <div key={log.id} className="border border-[#f1f5f9] rounded-2xl p-4 bg-[#f8fafc]/50 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div className="min-w-0">
                    <p className="font-body text-sm font-bold text-[#13284A] truncate">
                      {log.leads?.name || "Unnamed Lead"} ({formatPhone(log.leads?.phone || "")})
                    </p>
                    <p className="font-label text-xs text-[#475569] mt-1">
                      {pendingCallLabel(log)} · {log.duration_seconds || 0}s · {formatIstWhen(new Date(log.created_at), new Date())}
                    </p>
                  </div>
                  <button
                    onClick={() => openWrapupFromLog(log)}
                    className="px-4 py-2 bg-primary hover:bg-primary-dark text-white rounded-xl font-label text-xs font-bold transition-all shadow-sm shrink-0"
                  >
                    Wrap Up
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
