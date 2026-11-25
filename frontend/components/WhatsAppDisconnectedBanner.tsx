"use client";
import Link from "next/link";
import useSWR from "swr";
import { WifiOff } from "lucide-react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { canReconnect, connectionStatusApi, disconnectedMessage } from "@/lib/connectionStatusApi";

/**
 * v9.2 #23: a red bar across the dashboard while a WhatsApp number is disconnected, with one tap to the
 * Connect accounts page. Only the owner (or someone who can change settings) sees it, since only they can fix it.
 * A failed check shows nothing, and it re-checks every minute so the bar goes away once the number is back.
 */
export function WhatsAppDisconnectedBanner() {
  const { role, permissions, loading } = useAuthRole();
  const allowed = !loading && canReconnect(role, permissions);
  const { data } = useSWR(allowed ? "connection-status:whatsapp" : null, connectionStatusApi.whatsapp, {
    refreshInterval: 60_000,
    shouldRetryOnError: false,
  });
  if (!allowed || !data?.disconnected) return null;

  return (
    <div role="alert" className="sticky top-14 z-30 flex items-center gap-3 border-b border-red-300 bg-red-600 px-3 py-2 text-white md:top-16 md:px-5 md:py-2.5">
      <WifiOff size={18} className="shrink-0" aria-hidden />
      <p className="min-w-0 flex-1 truncate text-[13px] font-bold md:text-sm">{disconnectedMessage(data)}</p>
      <Link
        href="/dashboard/settings/connect-channels"
        className="inline-flex h-8 shrink-0 items-center rounded-lg bg-white px-4 text-xs font-bold text-red-700 transition-colors hover:bg-red-50"
      >
        Reconnect
      </Link>
    </div>
  );
}
