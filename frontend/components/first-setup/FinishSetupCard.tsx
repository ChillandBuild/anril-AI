"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, ListChecks } from "lucide-react";
import { firstSetupApi } from "@/lib/firstSetupApi";
import { finishSetupCard } from "./helpers";

/**
 * Home card: "Finish setup (3 of 6 done)". It links to the first-setup steps and disappears once all 6 are
 * done. It shows nothing while loading, or when the person may not change settings (the server says no),
 * so nobody sees a card they cannot act on.
 */
export function FinishSetupCard() {
  const [doneSteps, setDoneSteps] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    firstSetupApi
      .progress()
      .then((p) => !cancelled && setDoneSteps(p.already_live ? null : (p.done_steps ?? [])))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (doneSteps === null) return null;
  const card = finishSetupCard(doneSteps);
  if (card.finished) return null;

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
