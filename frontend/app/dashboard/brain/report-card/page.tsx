"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PeriodPicker } from "@/components/ai-setup/PeriodPicker";
import { NoAccess, SetupShell, useSetupAccess } from "@/components/ai-setup/SetupShell";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { aiSetupApi, percentLabel, rupees, safeFixHref, type Period, type ReportCard } from "@/lib/aiSetupApi";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card">
      <p className="font-label text-xs font-bold text-ink-secondary">{label}</p>
      <p className="mt-1 font-display text-2xl font-bold text-ink">{value}</p>
      {hint && <p className="mt-1 font-body text-xs text-ink-secondary">{hint}</p>}
    </div>
  );
}

export default function ReportCardPage() {
  const { loading: roleLoading, canView } = useSetupAccess();
  const { role } = useAuthRole();
  const isCaller = role === "caller"; // the endpoint answers 403 for telecallers
  const [period, setPeriod] = useState<Period>("30d");
  const [card, setCard] = useState<ReportCard | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!canView || isCaller) return;
    let live = true;
    aiSetupApi.reportCard(period).then((c) => { if (live) { setCard(c); setFailed(false); } }).catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [canView, isCaller, period]);

  if (roleLoading) return <div className="m-6 min-h-[320px] animate-pulse rounded-2xl bg-border-subtle" />;
  if (!canView) return <NoAccess />;
  if (isCaller) {
    return (
      <SetupShell title="AI report card" intro="How the AI agent did with your customers.">
        <p className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink-secondary">Not available for telecallers.</p>
      </SetupShell>
    );
  }

  return (
    <SetupShell
      title="AI report card"
      intro="How the AI agent did with your customers."
      right={<PeriodPicker value={period} onChange={(p) => { setCard(null); setPeriod(p); }} />}
    >
      {failed && <p role="alert" className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink-secondary">Could not load this. Please refresh.</p>}
      {!card && !failed && <div className="min-h-[200px] animate-pulse rounded-2xl bg-border-subtle" />}
      {card && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Tile label="Chats" value={String(card.chats)} />
            <Tile label="Handled alone" value={percentLabel(card.handled_alone_pct)}
              hint={card.chats === 0 ? "No chats in this period yet." : "The AI agent answered and no person was needed."} />
            <Tile label="Passed to a person" value={String(card.passed_to_person)} />
            <Tile label="Wrong answers" value={String(card.wrong_answers)} hint="Replies you gave a thumbs-down in Chats." />
            {card.revenue_from_ai_paise !== undefined && (
              <Tile label="Sales from AI chats" value={rupees(card.revenue_from_ai_paise)} hint="Paid orders the AI agent closed, before GST." />
            )}
          </div>
          <section className="card" aria-labelledby="fix-h">
            <h2 id="fix-h" className="font-display text-base font-bold text-ink">Fix these</h2>
            {card.fix_these.length === 0 ? (
              <p className="mt-2 font-body text-sm text-ink-secondary">Nothing to fix right now.</p>
            ) : (
              <ul className="mt-2 divide-y divide-border-subtle">
                {card.fix_these.map((fix) => (
                  <li key={fix.kind} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                    <p className="min-w-0 flex-1 font-body text-sm text-ink">{fix.text}</p>
                    <Link href={safeFixHref(fix.href)} className="btn-secondary min-h-9 shrink-0">Fix</Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </SetupShell>
  );
}
