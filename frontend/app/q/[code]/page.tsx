"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Loader2 } from "lucide-react";

// The page a printed QR opens. No sign-in. It asks the server where to send the customer
// (WhatsApp, with the first message filled in) and goes there.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://aira-ai-5tfr.onrender.com";

type State = { kind: "loading" } | { kind: "open"; url: string } | { kind: "gone" } | { kind: "error" };

export default function QrRedirectPage() {
  const { code } = useParams<{ code: string }>();
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/public/qr/${encodeURIComponent(code)}`, { cache: "no-store" });
        if (cancelled) return;
        if (res.status === 404) return setState({ kind: "gone" });
        if (!res.ok) return setState({ kind: "error" });
        const body = (await res.json()) as { wa_url?: string };
        if (!body.wa_url || !body.wa_url.startsWith("https://wa.me/")) return setState({ kind: "error" });
        setState({ kind: "open", url: body.wa_url });
        window.location.replace(body.wa_url);
      } catch {
        if (!cancelled) setState({ kind: "error" });
      }
    })();
    return () => { cancelled = true; };
  }, [code]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-white px-4">
      <div className="w-full max-w-sm text-center" aria-live="polite">
        {state.kind === "loading" && <Message icon title="Opening WhatsApp…" />}
        {state.kind === "open" && (
          <>
            <Message icon title="Opening WhatsApp…" />
            <p className="mt-2 text-sm text-slate-600">Nothing happened?</p>
            <a href={state.url} className="mt-3 inline-flex min-h-12 items-center justify-center rounded-xl bg-teal-700 px-6 text-base font-semibold text-white hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700">
              Open WhatsApp
            </a>
          </>
        )}
        {state.kind === "gone" && <Message title="This QR is no longer in use" body="Ask the shop for their new QR or phone number." />}
        {state.kind === "error" && (
          <>
            <Message title="Couldn't open this right now" body="Check your internet and scan again in a moment." />
            <button type="button" onClick={() => window.location.reload()} className="mt-3 inline-flex min-h-12 items-center rounded-xl border border-slate-300 px-6 text-base font-semibold text-slate-800">Try again</button>
          </>
        )}
      </div>
    </main>
  );
}

function Message({ title, body, icon }: { title: string; body?: string; icon?: boolean }) {
  return (
    <div>
      {icon && <Loader2 className="mx-auto mb-3 animate-spin text-slate-400" aria-hidden />}
      <h1 className="text-lg font-semibold text-slate-900">{title}</h1>
      {body && <p className="mt-1 text-sm text-slate-600">{body}</p>}
    </div>
  );
}
