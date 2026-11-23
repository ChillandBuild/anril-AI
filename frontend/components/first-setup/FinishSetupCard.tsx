"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Link2, ListChecks } from "lucide-react";
import { firstSetupApi } from "@/lib/firstSetupApi";
import { finishSetupCard, homeSetupCardKind } from "./helpers";

/**
 * Home card: "Finish setup (3 of 6 done)". It links to the first-setup steps and disappears once all 6 are
 * done. It shows nothing while loading, or when the person may not change settings (the server says no),
 * so nobody sees a card they cannot act on.
 * When the owner moved past step 5 without connecting, it says so instead (screen 86): nothing replies
 * to customers until Meta is connected, so that one step matters most.
 */
export function FinishSetupCard() {
  const [doneSteps, setDoneSteps] = useState<string[] | null>(null);
  const [step, setStep] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    firstSetupApi
      .progress()
      .then((p) => {
        if (cancelled) return;
        setDoneSteps(p.already_live ? null : (p.done_steps ?? []));
        setStep(p.step ?? null);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (doneSteps === null) return null;
  const kind = homeSetupCardKind(doneSteps, step);
  if (kind === "none") return null;
  const card = finishSetupCard(doneSteps);

  if (kind === "connect")
    return (
      <div className="rounded-2xl border border-primary/30 bg-white px-4 py-4 shadow-sm">
        <p className="font-label text-sm font-bold text-[#13284A]">🔌 You skipped one step: connect your accounts</p>
        <p className="mt-0.5 font-label text-xs text-[#556274]">Your AI agent starts replying to customers once Meta is connected. It takes about 5 minutes.</p>
        <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-[#e2e8f0] pt-3">
          <Link2 size={18} className="shrink-0 text-primary" aria-hidden="true" />
          <span className="min-w-0 flex-1 font-label text-xs text-[#556274]">
            <span className="block text-sm font-bold text-[#13284A]">Connect with Meta</span>
            WhatsApp, Instagram, Facebook and Meta Ads in one go. Razorpay for payment links is on the same page.
          </span>
          <Link href="/dashboard/settings/connect-channels" className="btn-primary min-h-9">
            Connect
          </Link>
        </div>
        <p className="mt-3 rounded-xl bg-primary/5 px-3 py-2 font-label text-xs text-[#13284A]">
          💡 Numbers like money in today, chats and bookings show here once customers start messaging.
        </p>
      </div>
    );

  return (
    <Link
      href="/dashboard/onboarding"
      className="flex min-h-14 items-center gap-3 rounded-2xl border border-[#e2e8f0] bg-white px-4 py-3 shadow-sm transition-colors hover:border-primary"
    >
      <ListChecks size={20} className="shrink-0 text-primary" aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <span className="block font-label text-sm font-bold text-[#13284A]">{card.title}</span>
        <span className="block font-label text-xs text-[#556274]">A few quick questions get your business ready to sell.</span>
      </span>
      <span className="shrink-0 text-primary" aria-hidden="true">
        <ArrowRight size={18} />
      </span>
    </Link>
  );
}
