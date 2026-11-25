"use client";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useRouter, usePathname } from "next/navigation";
import { Phone, X, Clock, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useActiveCall } from "@/app/dashboard/contexts/ActiveCallContext";
import { fetchTodayCallbacks, markCallbackDone } from "@/app/dashboard/telecalling/lib/notes-api";
import type { CallbackJob } from "@/app/dashboard/telecalling/types";

export function CallbackNotifier() {
  const { role, callerId } = useAuthRole();
  const { setActiveCall } = useActiveCall();
  const router = useRouter();
  const pathname = usePathname();

  const [dueCallbacks, setDueCallbacks] = useState<CallbackJob[]>([]);
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set());
  const [callingId, setCallingId] = useState<string | null>(null);

  const checkCallbacks = useCallback(async () => {
    // Only poll for callers who are logged in
    if (role !== "caller" || !callerId) return;

    try {
      const todayJobs = await fetchTodayCallbacks();
      const now = new Date();

      const due = todayJobs.filter((job) => {
        // Must be assigned to this caller
        const isAssigned = job.lead?.assigned_to === callerId;
        if (!isAssigned) return false;

        // Must be scheduled in the past or right now (due)
        const scheduledTime = new Date(job.scheduled_for);
        const isPastOrNow = scheduledTime <= now;

        // Must not be dismissed yet
        const isNotDismissed = !dismissedIds.has(job.id);

        return isPastOrNow && isNotDismissed;
      });

      setDueCallbacks(due);
    } catch (err) {
      console.error("CallbackNotifier poll error:", err);
    }
  }, [role, callerId, dismissedIds]);

  // Run on mount or when callerId changes
  useEffect(() => {
    if (role === "caller" && callerId) {
      checkCallbacks();
    } else {
      setDueCallbacks([]);
    }
  }, [role, callerId, checkCallbacks]);

  // Poll every 60 seconds
  usePolling(checkCallbacks, 60_000, role === "caller" && !!callerId);

  const handleDismiss = (id: string) => {
    setDismissedIds((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
    setDueCallbacks((prev) => prev.filter((cb) => cb.id !== id));
  };

  const handleCall = async (cb: CallbackJob) => {
    if (!callerId) return;
    setCallingId(cb.id);

    try {
      // 1. Initiate the call via TeleCMI / Backend
      const res = await api.calls.initiate({ leadId: cb.lead_id }, callerId);

      // 2. Mark the callback job as completed
      await markCallbackDone(cb.id);

      // 3. Set the global active call context so the notes panel pops up
      setActiveCall({
        leadId: res.lead_id ?? cb.lead_id,
        name: res.lead_name ?? cb.lead.name,
        phone: cb.lead.phone,
        callLogId: res.call_log_id ?? null,
      });

      toast.success(`Calling ${cb.lead.name || "Lead"}...`);

      // 4. Redirect to telecalling dashboard if they are on another page
      if (pathname !== "/dashboard/telecalling") {
        router.push("/dashboard/telecalling");
      }

      // 5. Remove from due list
      setDueCallbacks((prev) => prev.filter((item) => item.id !== cb.id));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to initiate callback call");
    } finally {
      setCallingId(null);
    }
  };

  if (dueCallbacks.length === 0) return null;

  return (
    <div className="pointer-events-none fixed inset-x-3 bottom-[calc(var(--mobile-nav-h)+env(safe-area-inset-bottom)+0.75rem)] z-[9999] max-w-md space-y-3 lg:inset-x-auto lg:bottom-6 lg:left-6 lg:w-full">
      {dueCallbacks.map((cb) => {
        const timeStr = new Date(cb.scheduled_for).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        });

        return (
          <div
            key={cb.id}
            className="pointer-events-auto w-full bg-surface-low/95 backdrop-blur-md border border-amber-500/80 rounded-2xl shadow-[0_10px_30px_rgba(245,158,11,0.25)] p-5 flex flex-col gap-4 animate-slide-up transition-all duration-300 ring-1 ring-amber-500/20"
          >
            {/* Header: Title & Close */}
            <div className="flex items-start justify-between gap-3">
              <div className="flex gap-3">
                <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-600 shrink-0 relative">
                  <Clock size={18} className="animate-pulse" />
                  <span className="absolute -top-1 -right-1 w-3 h-3 bg-amber-500 rounded-full border-2 border-surface-low animate-ping" />
                  <span className="absolute -top-1 -right-1 w-3 h-3 bg-amber-500 rounded-full border-2 border-surface-low" />
                </div>
                <div>
                  <h3 className="font-display font-bold text-sm text-on-surface leading-tight">
                    ⏰ Time to call {cb.lead.name || "Unnamed"}!
                  </h3>
                  <p className="font-label text-xs text-amber-600 font-semibold mt-1">
                    Scheduled for {timeStr}
                  </p>
                </div>
              </div>
              <button
                onClick={() => handleDismiss(cb.id)}
                className="p-1 rounded-lg text-on-surface-muted hover:bg-surface-mid transition-colors"
                title="Dismiss reminder"
              >
                <X size={15} />
              </button>
            </div>

            {/* Note body */}
            {cb.message_preview && (
              <div className="bg-surface-mid/50 border border-surface-mid/30 rounded-xl p-3 flex gap-2 items-start">
                <AlertCircle size={14} className="text-on-surface-muted shrink-0 mt-0.5" />
                <p className="font-body text-xs text-on-surface-muted leading-relaxed italic">
                  &ldquo;{cb.message_preview}&rdquo;
                </p>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-2.5">
              <button
                onClick={() => handleCall(cb)}
                disabled={callingId === cb.id}
                className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-primary hover:bg-primary-dark active:scale-[0.98] text-white font-label text-xs font-bold rounded-xl transition-all shadow-md shadow-primary/30 disabled:opacity-50"
              >
                <Phone size={13} className={callingId === cb.id ? "animate-bounce" : ""} />
                {callingId === cb.id ? "Connecting..." : "Call Now"}
              </button>
              <button
                onClick={() => handleDismiss(cb.id)}
                className="px-4 py-2.5 bg-surface border border-surface-mid hover:bg-surface-high text-on-surface-muted hover:text-on-surface font-label text-xs font-semibold rounded-xl transition-colors"
              >
                Dismiss
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
