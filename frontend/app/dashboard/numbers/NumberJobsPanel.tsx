"use client";

import { useState } from "react";
import { BellRing, KeyRound, Megaphone, Phone, Sparkles, Star } from "lucide-react";
import { Select, type SelectOption } from "@/components/ui/Select";

/** Which number does what (GET /api/v1/numbers -> jobs). picks: the number chosen per job, null = Automatic. */
export type PickJob = "alerts" | "otp" | "reach";
export type NumberJobs = {
  default_sender_id: string | null;
  main_id: string | null;
  reach_ids: string[];
  picks?: Partial<Record<PickJob, string | null>>;
};

export type JobNumber = {
  id: string;
  display_name: string;
  number: string;
  role: string;
  /** Why it can't be picked for Reach right now (null = it can). */
  reach_block?: string | null;
  /** Why it can't send alerts or OTP codes (null = it can). */
  send_block?: string | null;
};

/** The three jobs that can have their own number (backend: services/number_jobs.py). */
export const PICK_ROWS: { job: PickJob; label: string; detail: string }[] = [
  { job: "reach", label: "Reach campaigns", detail: "Broadcasts and sheet uploads" },
  { job: "otp", label: "OTP codes", detail: "Login and verification codes" },
  { job: "alerts", label: "Alerts to you and staff", detail: "Hot leads, human help, evening summary" },
];

const JOB_ICON: Record<PickJob, { icon: React.ElementType; tile: string }> = {
  reach: { icon: Megaphone, tile: "bg-orange-50 text-orange-600 ring-orange-100" },
  otp: { icon: KeyRound, tile: "bg-violet-50 text-violet-600 ring-violet-100" },
  alerts: { icon: BellRing, tile: "bg-amber-50 text-amber-600 ring-amber-100" },
};

/** Today's cap running out keeps a Reach pick (the rest waits); anything else sends it back to Automatic. */
const KEEPS_REACH_PICK = "Today's cap used";

export type PickState = { picked: JobNumber | null; inUse: boolean; why: string | null };

/** The number picked for a job, and whether the senders are really using it right now. */
export function pickState(job: PickJob, jobs: NumberJobs | null, numbers: JobNumber[]): PickState {
  const picked = numbers.find((n) => n.id === jobs?.picks?.[job]) ?? null;
  if (!picked) return { picked: null, inUse: false, why: null };
  const why = (job === "reach" ? picked.reach_block : picked.send_block) ?? null;
  return { picked, inUse: !why || (job === "reach" && why === KEEPS_REACH_PICK), why };
}

const AUTO = "auto";
const last5 = (n: JobNumber) => n.number.replace(/\D/g, "").slice(-5);

function NumberLabel({ n, why }: { n: JobNumber; why: string | null }) {
  const main = n.role === "primary";
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <span
        aria-hidden="true"
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${main ? "bg-amber-100 text-amber-600" : "bg-primary-50 text-primary"}`}
      >
        {main ? <Star size={12} className="fill-current" /> : <Phone size={12} />}
      </span>
      <span className="truncate font-semibold text-ink">{n.display_name}</span>
      <span className="shrink-0 font-mono text-[12px] text-ink-muted">··{last5(n)}</span>
      {main && <span className="shrink-0 rounded-full bg-amber-50 px-1.5 py-px text-[10.5px] font-bold uppercase tracking-wide text-amber-700">Main</span>}
      {why && <span className="shrink-0 text-[12px] font-medium text-red-600">· {why}</span>}
    </span>
  );
}

function AutoLabel({ job, main }: { job: PickJob; main: JobNumber | undefined }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <span aria-hidden="true" className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-600">
        <Sparkles size={12} />
      </span>
      <span className="font-semibold text-ink">Automatic</span>
      <span className="truncate text-[12.5px] text-ink-muted">
        {job === "reach" ? "Main, Standby as backup" : main ? `Main ··${last5(main)}` : "Main"}
      </span>
    </span>
  );
}

/** Dropdown choices: Automatic, then every number; a number that can't do the job is greyed out with why. */
export function pickOptions(job: PickJob, jobs: NumberJobs | null, numbers: JobNumber[]): SelectOption[] {
  const main = numbers.find((n) => n.id === (job === "reach" ? jobs?.main_id : jobs?.default_sender_id ?? jobs?.main_id));
  const current = jobs?.picks?.[job] ?? null;
  return [
    { value: AUTO, label: <AutoLabel job={job} main={main} />, text: "Automatic" },
    ...numbers.map((n) => {
      const why = (job === "reach" ? n.reach_block : n.send_block) ?? null;
      const name = `${n.display_name} ${last5(n)}`;
      return {
        value: n.id,
        text: why ? `${name} — ${why}` : name,
        label: <NumberLabel n={n} why={why} />,
        // The current pick stays choosable so the menu can show it; others are greyed out.
        disabled: !!why && n.id !== current,
      };
    }),
  ];
}

/** A short line under a pick that can't be used right now. */
function PickNote({ job, state }: { job: PickJob; state: PickState }) {
  if (!state.picked || !state.why) return null;
  const who = `${state.picked.display_name} ··${last5(state.picked)}`;
  const text = state.inUse
    ? `${who} has used today's cap. The rest waits until it has room again.`
    : `${who} can't send now (${state.why}), so ${job === "reach" ? "Main, then Standby" : "Main"} sends instead.`;
  return <p className="mt-2 rounded-lg bg-amber-50 px-2.5 py-1.5 font-body text-xs leading-snug text-amber-800">{text}</p>;
}

/** "Which number does what": a number for Reach, OTP codes and alerts. Everything else follows the default rule. */
export function NumberJobsPanel({
  jobs,
  numbers,
  canManage = false,
  onPick,
}: {
  jobs: NumberJobs | null;
  numbers: JobNumber[];
  canManage?: boolean;
  onPick?: (job: PickJob, numberId: string | null) => Promise<void>;
}) {
  const [saving, setSaving] = useState<PickJob | null>(null);

  async function pick(job: PickJob, value: string) {
    if (!onPick) return;
    setSaving(job);
    try {
      await onPick(job, value === AUTO ? null : value);
    } finally {
      setSaving(null);
    }
  }

  return (
    <aside className="rounded-2xl bg-surface p-5 shadow-card ring-1 ring-[#c4c7c7]/15 md:rounded-card md:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="font-display text-lg font-bold text-on-surface">Which number does what</h2>
        <span className="font-body text-xs text-on-surface-muted">Pick a number for each job</span>
      </div>
      {/* One column beside the numbers on wide screens; three side by side above them otherwise */}
      <ul className="mt-4 grid gap-3 md:grid-cols-3 2xl:grid-cols-1">
        {PICK_ROWS.map((r) => {
          const Icon = JOB_ICON[r.job].icon;
          return (
            <li key={r.job} className="rounded-xl border border-border/70 bg-white p-3.5">
              <div className="mb-3 flex items-center gap-3">
                <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-1 ${JOB_ICON[r.job].tile}`} aria-hidden="true">
                  <Icon size={17} />
                </span>
                <span className="min-w-0">
                  <span className="block truncate font-body text-sm font-semibold text-on-surface">{r.label}</span>
                  <span className="block truncate font-body text-xs text-on-surface-muted">{r.detail}</span>
                </span>
              </div>
              <Select
                aria-label={`Number for ${r.label}`}
                className="h-11 rounded-xl"
                disabled={!canManage || !onPick || saving === r.job}
                value={jobs?.picks?.[r.job] ?? AUTO}
                onChange={(v) => pick(r.job, v)}
                options={pickOptions(r.job, jobs, numbers)}
              />
              <PickNote job={r.job} state={pickState(r.job, jobs, numbers)} />
            </li>
          );
        })}
      </ul>
      <p className="mt-4 font-body text-xs leading-relaxed text-on-surface-muted">
        Everything else follows the usual rule: a reply goes from the number the customer wrote to, the rest from your Main
        number. Greyed-out numbers can&apos;t be picked right now. If Meta rates Main red, a connected Standby number becomes
        Main by itself.
      </p>
    </aside>
  );
}
