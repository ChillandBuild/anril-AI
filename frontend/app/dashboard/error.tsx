"use client";
import { useEffect } from "react";
import { RefreshCw, AlertTriangle } from "lucide-react";
import { reportClientError } from "@/lib/connectionStatusApi";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Dashboard render error:", error);
    // v9.2 #24: tell Anril support (code and page only), once per browser session.
    reportClientError(error?.digest, window.location.pathname);
  }, [error]);

  const isNetwork =
    /reach server|failed to fetch|networkerror|load failed/i.test(error?.message || "");

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] px-6 text-center">
      <div className="w-14 h-14 rounded-2xl bg-rose-100 text-rose-600 flex items-center justify-center mb-5">
        <AlertTriangle size={26} />
      </div>
      <h2 className="font-display text-xl font-extrabold text-[#0A1528] tracking-tight">
        {isNetwork ? "Can't reach the server" : "Something went wrong"}
      </h2>
      <p className="font-body text-sm text-[#475569] max-w-md mt-2 leading-relaxed">
        {isNetwork
          ? "The backend may be waking up or briefly unavailable. Your data is safe — give it a few seconds and retry."
          : "This page hit a problem. Nothing you saved is lost. Try again, and if it keeps happening tell the Anril team the code below."}
      </p>
      <button
        onClick={reset}
        className="mt-6 flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-primary to-primary-dark text-white rounded-2xl font-label text-sm font-bold transition-all shadow-sm hover:scale-[1.02] active:scale-[0.98]"
      >
        <RefreshCw size={15} />
        Try again
      </button>
      {error?.digest ? (
        <p className="font-body text-xs text-[#475569] mt-4">Code: {error.digest}</p>
      ) : null}
    </div>
  );
}
