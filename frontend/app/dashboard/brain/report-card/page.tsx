"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PeriodPicker } from "@/components/ai-setup/PeriodPicker";
import { NoAccess, SetupShell, useSetupAccess } from "@/components/ai-setup/SetupShell";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { aiSetupApi, percentLabel, rupees, safeFixHref, splitChats, type Period, type ReportCard } from "@/lib/aiSetupApi";

const RADIUS = 54;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

const FIX_KINDS: Record<string, { pill: string; button: string }> = {
  couldnt_answer: { pill: "Couldn't answer", button: "Answer" },
  wrong_answers: { pill: "Wrong answer", button: "Fix" },
  knowledge: { pill: "Knowledge", button: "Open" },
  tone: { pill: "Tone", button: "Change" },
};

function Ring({ pct, alone, chats }: { pct: number | null; alone: number; chats: number }) {
  const filled = pct === null ? 0 : (CIRCUMFERENCE * Math.min(Math.max(pct, 0), 100)) / 100;
  return (
    <svg width="150" height="150" viewBox="0 0 150 150" role="img" aria-label={`Handled alone ${percentLabel(pct)}`} className="shrink-0">
      <circle cx="75" cy="75" r={RADIUS} fill="none" stroke="#eef2f6" strokeWidth="16" />
      <circle cx="75" cy="75" r={RADIUS} fill="none" stroke="#038285" strokeWidth="16" strokeLinecap="round"
        strokeDasharray={`${filled} ${CIRCUMFERENCE}`} transform="rotate(-90 75 75)" opacity={filled > 0 ? 1 : 0}>
        <title>{`${alone} of ${chats} chats handled with no person needed`}</title>
      </circle>
      <text x="75" y="76" textAnchor="middle" fontSize="30" fontWeight="800" fill="#0A1528">{percentLabel(pct)}</text>
      <text x="75" y="98" textAnchor="middle" fontSize="12" fill="#475569">handled alone</text>
    </svg>
  );
}

function SplitBar({ parts }: { parts: { label: string; value: number; color: string }[] }) {
  const shown = parts.filter((p) => p.value > 0);
  return (
    <div className="min-w-0 flex-[1_1_260px]">
      <div className="flex h-[18px] gap-0.5" role="img" aria-label={parts.map((p) => `${p.label} ${p.value}`).join(", ")}>
        {shown.map((p, i) => (
          <div key={p.label} title={`${p.label}: ${p.value}`} style={{ flex: p.value, background: p.color }}
            className={`${i === 0 ? "rounded-l-[5px]" : ""} ${i === shown.length - 1 ? "rounded-r-[5px]" : ""}`} />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-body text-xs text-ink-secondary">
        {parts.map((p) => (
          <li key={p.label} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: p.color }} aria-hidden />
            {p.label} <b className="text-ink">{p.value}</b>
          </li>
        ))}
      </ul>
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
      <SetupShell>
        <p className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink-secondary">Not available for telecallers.</p>
      </SetupShell>
    );
  }

  const split = card ? splitChats(card) : null;

  return (
    <SetupShell toolbar={<PeriodPicker value={period} onChange={(p) => { setCard(null); setPeriod(p); }} />}>
      {failed && <p role="alert" className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink-secondary">Could not load this. Please refresh.</p>}
      {!card && !failed && <div className="min-h-[200px] animate-pulse rounded-2xl bg-border-subtle" />}
      {card && split && (
        <>
          <div className="flex flex-wrap items-stretch gap-4">
            <section className="card flex min-w-0 flex-[2_1_520px] flex-col gap-3" aria-labelledby="chats-h">
              <h2 id="chats-h" className="font-display text-base font-bold text-ink">{card.chats} {card.chats === 1 ? "chat" : "chats"}</h2>
              {card.chats === 0 ? (
                <p className="font-body text-sm text-ink-secondary">No chats in this period yet.</p>
              ) : (
                <div className="flex flex-wrap items-center gap-6">
                  <Ring pct={card.handled_alone_pct} alone={split.alone} chats={card.chats} />
                  <SplitBar parts={[
                    { label: "Handled alone", value: split.alone, color: "#038285" },
                    { label: "Passed to a person", value: split.person, color: "#d97706" },
                    { label: "Couldn't answer", value: split.couldnt, color: "#e11d48" },
                  ]} />
                </div>
              )}
            </section>
            {card.revenue_from_ai_paise !== undefined && (
              <section className="card flex min-w-0 flex-[1_1_300px] flex-col gap-2" aria-labelledby="sales-h">
                <h2 id="sales-h" className="font-display text-base font-bold text-ink">Sales from AI chats</h2>
                <p className="font-display text-3xl font-bold text-ink">{rupees(card.revenue_from_ai_paise)}</p>
                <p className="font-body text-xs text-ink-secondary">Paid orders the AI agent closed, before GST</p>
              </section>
            )}
          </div>
          <section className="card flex flex-wrap items-start gap-3 !py-0 !pl-2" aria-labelledby="fix-h">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/login/healy-poster.png" alt="" width={150} height={150} className="h-[150px] w-[150px] shrink-0 object-contain" />
            <div className="min-w-0 flex-[1_1_400px] py-[18px]">
              <h2 id="fix-h" className="font-display text-base font-bold text-ink">Fix these</h2>
              <p className="font-body text-xs text-ink-secondary">Each fix makes the AI agent better next time.</p>
              {card.fix_these.length === 0 ? (
                <p className="mt-3 font-body text-sm text-ink-secondary">Nothing to fix right now.</p>
              ) : (
                <ul className="mt-2">
                  {card.fix_these.map((fix) => {
                    const kind = FIX_KINDS[fix.kind] ?? { pill: "Fix", button: "Fix" };
                    return (
                      <li key={fix.kind} className="flex flex-wrap items-center gap-3 border-t border-border-subtle py-3">
                        <span className="rounded-full bg-slate-100 px-2.5 py-0.5 font-label text-xs font-bold text-ink-secondary">{kind.pill}</span>
                        <p className="min-w-0 flex-1 font-body text-sm text-ink">{fix.text}</p>
                        <Link href={safeFixHref(fix.href)} className="btn-secondary min-h-9 shrink-0">{kind.button}</Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </section>
        </>
      )}
    </SetupShell>
  );
}
