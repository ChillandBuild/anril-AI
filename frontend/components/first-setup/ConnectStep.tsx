"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, IndianRupee, Link2, X } from "lucide-react";
import { PHONE } from "@/components/site/content";
import { connectLinkFor, type WhatsAppUse } from "./helpers";

/**
 * First setup, step 5 (v9.2 screens 87, 90): "How do you want to use WhatsApp?" in plain words, then one
 * "Connect with Meta" that opens the Connect accounts page with the matching button pointed out.
 * The Meta login itself stays on that page: it is the one place that runs Meta's signup window.
 */

const CHOICES: { value: WhatsAppUse; title: string; tag?: string; text: string }[] = [
  {
    value: "keep_phone",
    title: "In Anril + keep my phone app",
    tag: "Most shops pick this",
    text: "Your current number. The WhatsApp Business app keeps working.",
  },
  { value: "anril_only", title: "Only in Anril", text: "No phone app on this number. Most pick a new number for this." },
];

function Point({ warn, children }: { warn?: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      {warn ? (
        <span className="mt-0.5 w-4 shrink-0 text-center font-bold text-amber-600" aria-hidden>
          !
        </span>
      ) : (
        <Check size={16} className="mt-0.5 shrink-0 text-primary" aria-hidden />
      )}
      <span>{children}</span>
    </li>
  );
}

/** Screen 90: "What's the difference?" between keeping the phone app and using Anril only. */
export function WhatsAppCompareDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="wa-compare-title"
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-3xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <h2 id="wa-compare-title" className="font-display text-xl font-bold text-ink">
            How do you want to use WhatsApp?
          </h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1 text-ink-secondary hover:bg-border-subtle hover:text-ink">
            <X size={20} />
          </button>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border-2 border-primary bg-primary/5 p-4">
            <p className="font-body text-base font-bold text-ink">📱 In Anril + keep my phone app</p>
            <span className="mt-1 inline-block rounded-full bg-primary/10 px-2 py-0.5 font-body text-xs font-semibold text-primary">Most shops pick this</span>
            <ul className="mt-3 space-y-2 font-body text-sm text-ink">
              <Point>Uses your current number. Customers keep the number they know</Point>
              <Point>WhatsApp Business app on the phone keeps working</Point>
              <Point>Last 6 months of chats come into Anril</Point>
              <Point warn>Open the app at least once a week, or it can disconnect</Point>
            </ul>
          </div>
          <div className="rounded-2xl border border-border p-4">
            <p className="font-body text-base font-bold text-ink">💻 Only in Anril</p>
            <ul className="mt-3 space-y-2 font-body text-sm text-ink">
              <Point>Never disconnects. No phone to look after</Point>
              <Point>Best for big offer sending and a large team</Point>
              <Point>Most pick a new number, so your current WhatsApp stays as it is on the phone</Point>
              <Point warn>No WhatsApp app on this number</Point>
              <Point warn>Using your current number? Back up chats and delete WhatsApp on the phone first. Old chats don&apos;t move</Point>
            </ul>
          </div>
        </div>

        <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 p-3 font-body text-sm text-amber-900">
          <p className="font-semibold">For &quot;keep my phone app&quot;: is your number on the WhatsApp Business app? (the green app with a &quot;B&quot;)</p>
          <p className="mt-0.5">If it&apos;s on normal WhatsApp, switch it to WhatsApp Business first. It takes 2 minutes and keeps all your chats.</p>
        </div>

        <div className="mt-3 flex gap-2 rounded-2xl bg-border-subtle/60 p-3 font-body text-sm text-ink-secondary">
          <IndianRupee size={16} className="mt-0.5 shrink-0 text-ink" aria-hidden />
          <p>
            <span className="font-semibold text-ink">Cost is the same either way.</span> Meta charges for some messages sent from Anril, like offers
            (about ₹0.86 each, + GST). This is on top of your Anril plan.{" "}
            <Link href="/dashboard/settings/meta-charges" target="_blank" rel="noopener" className="font-semibold text-primary hover:underline">
              See Meta&apos;s charges
            </Link>
          </p>
        </div>

        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <a href={PHONE.whatsapp} target="_blank" rel="noopener noreferrer" className="btn-secondary">
            Talk to Anril team
          </a>
          <button type="button" onClick={onClose} className="btn-primary">
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}

export function ConnectStep({ onNext }: { onNext: () => void }) {
  const [use, setUse] = useState<WhatsAppUse>("keep_phone");
  const [compareOpen, setCompareOpen] = useState(false);

  return (
    <div className="card rounded-3xl p-8">
      <h1 className="font-display text-xl font-bold text-ink mb-1">Connect your WhatsApp and Instagram</h1>
      <p className="font-body text-sm text-ink-muted mb-6">
        One Facebook login connects WhatsApp, Instagram, Facebook and Meta Ads. Your AI agent can only reply after this.
      </p>

      <fieldset>
        <legend className="mb-2 font-body text-sm font-semibold text-ink">How do you want to use WhatsApp?</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {CHOICES.map((c) => (
            <label
              key={c.value}
              className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-4 ${use === c.value ? "border-2 border-primary bg-primary/5" : "border-border"}`}
            >
              <input type="radio" name="wa-use" value={c.value} checked={use === c.value} onChange={() => setUse(c.value)} className="mt-1 accent-[var(--primary-600)]" />
              <span className="font-body text-sm text-ink">
                <span className="block font-semibold">{c.title}</span>
                {c.tag && <span className="mt-0.5 inline-block rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">{c.tag}</span>}
                <span className="mt-1 block text-ink-secondary">{c.text}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <button type="button" onClick={() => setCompareOpen(true)} className="mt-2 font-body text-sm font-semibold text-primary hover:underline">
        What&apos;s the difference? ›
      </button>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Link href={connectLinkFor(use)} target="_blank" rel="noopener" className="btn-primary">
          <Link2 size={16} aria-hidden /> Connect with Meta
        </Link>
        <p className="min-w-0 flex-1 font-body text-xs text-ink-secondary">
          A Facebook window opens: log in, pick your business page and WhatsApp number, confirm on your phone.
        </p>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-border p-4">
        <p className="font-body text-sm text-ink">
          <span className="font-semibold">Connect Razorpay</span> <span className="text-ink-secondary">· optional</span>
          <span className="block text-ink-secondary">So the AI agent can send payment links. You can do this later.</span>
        </p>
        <Link href="/dashboard/settings/connect-channels" target="_blank" rel="noopener" className="btn-secondary">
          Connect
        </Link>
      </div>

      <p className="mt-4 rounded-2xl bg-amber-50 p-3 font-body text-sm text-amber-900">
        Stuck? The Anril team can do it with you on a call.{" "}
        <a href={PHONE.whatsapp} target="_blank" rel="noopener noreferrer" className="font-semibold text-primary hover:underline">
          WhatsApp us ›
        </a>
      </p>

      <button type="button" onClick={onNext} className="btn-primary mt-4 w-full justify-center">
        Done, next step
      </button>
      <p className="mt-2 text-center font-body text-xs text-ink-muted">Connect opens in a new tab, so you can come straight back here.</p>

      <WhatsAppCompareDialog open={compareOpen} onClose={() => setCompareOpen(false)} />
    </div>
  );
}
