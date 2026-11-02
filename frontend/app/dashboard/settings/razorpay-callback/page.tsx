"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { completeRazorpayOAuth } from "../connect-channels/api";

const CONNECT_CHANNELS = "/dashboard/settings/connect-channels";

type Status = { kind: "working" } | { kind: "done"; accountId: string } | { kind: "failed"; message: string };

/** Razorpay sends the browser here after the consent screen (the partner app's whitelisted
 *  redirect URI). The backend checks `state` against what /razorpay/oauth/start stored for
 *  this workspace, then swaps `code` for tokens. */
function RazorpayCallback() {
  const params = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState<Status>({ kind: "working" });
  // The code and state are single-use: React's dev double-run of effects must not send them twice.
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;

    const error = params.get("error");
    const code = params.get("code");
    const state = params.get("state");
    if (error || !code || !state) {
      setStatus({
        kind: "failed",
        message: error === "access_denied"
          ? "You declined access on Razorpay, so nothing was connected."
          : "Razorpay didn't complete the connection. Please try again.",
      });
      return;
    }

    completeRazorpayOAuth(code, state)
      .then(({ account_id }) => {
        setStatus({ kind: "done", accountId: account_id });
        toast.success("Razorpay connected");
        router.replace(CONNECT_CHANNELS);
      })
      .catch((e: unknown) => {
        setStatus({ kind: "failed", message: e instanceof Error ? e.message : "Razorpay connection failed." });
      });
  }, [params, router]);

  return (
    <div className="mx-auto mt-10 max-w-md rounded-3xl border border-primary-200/80 bg-white p-8 text-center shadow-[0_12px_40px_rgba(var(--primary-600-rgb),0.08)]">
      {status.kind === "working" && (
        <>
          <Loader2 size={28} className="mx-auto animate-spin text-primary" />
          <h1 className="mt-4 font-display text-lg font-bold text-ink">Connecting Razorpay…</h1>
        </>
      )}
      {status.kind === "done" && (
        <>
          <CheckCircle2 size={28} className="mx-auto text-emerald-600" />
          <h1 className="mt-4 font-display text-lg font-bold text-ink">Razorpay connected</h1>
          <p className="mt-1.5 font-body text-sm text-ink-muted">Account {status.accountId}</p>
        </>
      )}
      {status.kind === "failed" && (
        <>
          <AlertCircle size={28} className="mx-auto text-red-600" />
          <h1 className="mt-4 font-display text-lg font-bold text-ink">Razorpay wasn&apos;t connected</h1>
          <p className="mt-1.5 font-body text-sm text-ink-muted">{status.message}</p>
          <Link
            href={CONNECT_CHANNELS}
            className="mt-5 inline-flex rounded-lg bg-[#f4f0ff] px-3 py-2 font-label text-xs font-bold text-primary hover:bg-[var(--primary-100)]"
          >
            Back to Connect Channels
          </Link>
        </>
      )}
    </div>
  );
}

export default function RazorpayCallbackPage() {
  return (
    <Suspense fallback={<Loader2 size={28} className="mx-auto mt-10 animate-spin text-primary" />}>
      <RazorpayCallback />
    </Suspense>
  );
}
