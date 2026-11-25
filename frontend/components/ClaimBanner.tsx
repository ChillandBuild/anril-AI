"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useNotifications } from "@/hooks/useNotifications";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";

export function ClaimBanner() {
  const { role, callerId } = useAuthRole();
  const { pool, reload } = useNotifications();
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  if (role !== "caller" || pool.length === 0) return null;
  const item = pool[0];
  const extra = pool.length - 1;

  const claim = async () => {
    if (!callerId) { toast.error("No caller profile"); return; }
    setBusy(true);
    try {
      await api.chatHandovers.assign(item.id, callerId);
      toast.success("Claimed");
      await reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Already claimed");
      await reload();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sticky top-14 z-30 flex items-center gap-3 px-3 py-2 md:top-16 md:px-5 md:py-2.5 bg-gradient-to-r from-rose-50 to-pink-50 border-b border-rose-200">
      <AlertCircle size={18} className="text-rose-600 shrink-0" />
      <p className="min-w-0 flex-1 text-[13px] md:text-sm font-bold text-rose-900 truncate">
        Lead &quot;{item.lead_name || "Unknown"}&quot; needs a human — unclaimed.
        {extra > 0 && <span className="ml-2 text-rose-600 font-medium">+{extra} more in the pool</span>}
      </p>
      <button onClick={() => router.push("/dashboard/conversations")}
        className="inline-flex h-8 shrink-0 items-center px-3 text-xs font-bold text-rose-700 hover:bg-rose-100 rounded-lg transition-colors">
        View
      </button>
      <button onClick={claim} disabled={busy}
        className="inline-flex h-8 shrink-0 items-center px-4 text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 rounded-lg transition-colors disabled:opacity-50">
        {busy ? "Claiming…" : "Claim"}
      </button>
    </div>
  );
}
