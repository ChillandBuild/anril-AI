"use client";

import { useState } from "react";
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
export const PICK_ROWS: { job: PickJob; icon: string; label: string; detail: string }[] = [
  { job: "reach", icon: "📣", label: "Reach campaigns", detail: "Broadcasts and sheet uploads" },
  { job: "otp", icon: "🔐", label: "OTP codes", detail: "Login and verification codes" },
  { job: "alerts", icon: "🔔", label: "Alerts to you and staff", detail: "Hot leads, human help, evening summary" },
];

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
const last5 = (n: JobNumber) => n.number.slice(-5);

/** Dropdown choices: Automatic, then every number; a number that can't do the job is greyed out with why. */
export function pickOptions(job: PickJob, jobs: NumberJobs | null, numbers: JobNumber[]): SelectOption[] {
  const main = numbers.find((n) => n.id === (job === "reach" ? jobs?.main_id : jobs?.default_sender_id ?? jobs?.main_id));
  const autoLabel = job === "reach" ? "⭐ Main + backup" : `⭐ Main${main ? ` · ${last5(main)}` : ""}`;
  const current = jobs?.picks?.[job] ?? null;
  return [
    { value: AUTO, label: autoLabel, text: "Automatic" },
    ...numbers.map((n) => {
      const why = (job === "reach" ? n.reach_block : n.send_block) ?? null;
      const name = `${n.role === "primary" ? "⭐ " : ""}${n.display_name} · ${last5(n)}`;
      return {
        value: n.id,
        text: name,
        label: why ? `${name} — ${why}` : name,
        // The current pick stays choosable so the menu can show it; others are greyed out.
        disabled: !!why && n.id !== current,
      };
    }),
  ];
}

/** A short line under a pick that can't be used right now. */
function PickNote({ job, state }: { job: PickJob; state: PickState }) {
  if (!state.picked || !state.why) return null;
  const who = `${state.picked.display_name} ${last5(state.picked)}`;
  const text = state.inUse
    ? `${who} has used today's cap. The rest waits until it has room again.`
    : `${who} can't send now (${state.why}), so ${job === "reach" ? "Main, then Standby" : "Main"} sends instead.`;
  return <p className="mt-1.5 font-body text-xs leading-snug text-amber-700">{text}</p>;
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
      <h2 className="font-display text-lg font-bold text-on-surface">Which number does what</h2>
      {/* One column beside the numbers on wide screens; three side by side above them otherwise */}
      <ul className="mt-2 grid gap-x-6 divide-y divide-border/70 md:grid-cols-3 md:divide-y-0 2xl:grid-cols-1 2xl:divide-y">
        {PICK_ROWS.map((r) => (
          <li key={r.job} className="py-3">
            <div className="flex flex-col gap-2 2xl:flex-row 2xl:items-center 2xl:justify-between 2xl:gap-3">
              <div className="min-w-0 flex-1">
                <p className="font-body text-sm font-semibold text-on-surface">
                  <span aria-hidden="true">{r.icon}</span> {r.label}
                </p>
                <p className="font-body text-xs text-on-surface-muted">{r.detail}</p>
              </div>
              <Select
                size="sm"
                aria-label={`Number for ${r.label}`}
                className="w-full shrink-0 2xl:w-48"
                disabled={!canManage || !onPick || saving === r.job}
                value={jobs?.picks?.[r.job] ?? AUTO}
                onChange={(v) => pick(r.job, v)}
                options={pickOptions(r.job, jobs, numbers)}
              />
            </div>
            <PickNote job={r.job} state={pickState(r.job, jobs, numbers)} />
          </li>
        ))}
      </ul>
      <p className="mt-2 font-body text-xs leading-relaxed text-on-surface-muted">
        Everything else follows the usual rule: a reply goes from the number the customer wrote to, the rest from your Main
        number. Greyed-out numbers can&apos;t be picked right now. If Meta rates Main red, a connected Standby number becomes Main by itself.
      </p>
    </aside>
  );
}
