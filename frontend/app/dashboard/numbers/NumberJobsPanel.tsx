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

/** Who sends a job: one fixed number, the customer's own chat number, or a rotation. */
export type JobSender =
  | { kind: "number"; number: JobNumber | null }
  | { kind: "their-number" }
  | { kind: "rotation"; numbers: JobNumber[]; preferTheirs?: boolean };

export type JobRow = { icon: string; job: string; detail: string; sender: JobSender; pick?: PickJob };
export type JobGroup = { title: string; rows: JobRow[] };

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

/**
 * "Which number does what", written from how the sending code works (backend: meta_cloud._creds,
 * outbound_router, services/number_jobs.py). Alerts, OTP codes and Reach can be given their own
 * number; everything else follows the default rule.
 */
export function numberJobGroups(jobs: NumberJobs | null, numbers: JobNumber[]): JobGroup[] {
  const byId = (id: string | null | undefined) => numbers.find((n) => n.id === id) ?? null;
  const main = byId(jobs?.main_id);
  const sender = byId(jobs?.default_sender_id) ?? main;
  // Numbers that may send campaigns now (a used-up cap still counts: it sends again tomorrow)
  const pool = (jobs?.reach_ids ?? [])
    .map(byId)
    .filter((n): n is JobNumber => !!n && (!n.reach_block || n.reach_block === KEEPS_REACH_PICK));
  // Main first, as the campaign sender picks it
  pool.sort((a, b) => (a.role === "primary" ? -1 : b.role === "primary" ? 1 : 0));
  const fixed: JobSender = { kind: "number", number: sender };
  const pinned = (job: PickJob): JobSender => {
    const s = pickState(job, jobs, numbers);
    return s.inUse ? { kind: "number", number: s.picked } : fixed;
  };
  const reach = pickState("reach", jobs, numbers);

  return [
    {
      title: "Replies to a customer",
      rows: [
        { icon: "💬", job: "AI agent replies", detail: "Every chat the AI answers", sender: { kind: "their-number" } },
        { icon: "🧑‍💼", job: "Your team's replies in Chats", detail: "Messages, photos and files typed in a chat", sender: { kind: "their-number" } },
      ],
    },
    {
      title: "Campaigns",
      rows: [
        {
          icon: "📣", job: "Reach campaigns", detail: "Broadcasts and sheet uploads", pick: "reach",
          sender: reach.inUse ? { kind: "number", number: reach.picked } : { kind: "rotation", numbers: pool },
        },
        { icon: "🔁", job: "Bring-back messages", detail: "Re-engagement for quiet customers", sender: { kind: "rotation", numbers: pool, preferTheirs: true } },
      ],
    },
    {
      title: "Sent by Anril on its own",
      rows: [
        { icon: "🔔", job: "Alerts to you and staff", detail: "Hot leads, human help, evening summary", sender: pinned("alerts"), pick: "alerts" },
        { icon: "🔐", job: "OTP codes", detail: "Login and verification codes", sender: pinned("otp"), pick: "otp" },
        { icon: "🎯", job: "New leads from ads", detail: "Welcome message for Facebook and Instagram forms", sender: fixed },
        { icon: "🛒", job: "IndiaMART and JustDial leads", detail: "First message to a new enquiry", sender: fixed },
        { icon: "⚡", job: "Auto-Messages and follow-ups", detail: "Welcome, reminders, scheduled follow-ups", sender: fixed },
        { icon: "🧾", job: "Bills, orders and bookings", detail: "Bills, order updates, payment reminders, bookings", sender: fixed },
      ],
    },
  ];
}

const AUTO = "auto";
const last5 = (n: JobNumber) => n.number.slice(-5);

/** Dropdown choices: Automatic, then every number; a number that can't do the job is greyed out with why. */
export function pickOptions(job: PickJob, jobs: NumberJobs | null, numbers: JobNumber[]): SelectOption[] {
  const main = numbers.find((n) => n.id === (job === "reach" ? jobs?.main_id : jobs?.default_sender_id ?? jobs?.main_id));
  const autoLabel = job === "reach" ? "Automatic: Main, then Standby" : `Automatic: Main${main ? ` (${last5(main)})` : ""}`;
  const current = jobs?.picks?.[job] ?? null;
  return [
    { value: AUTO, label: autoLabel },
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

function NumberChip({ n }: { n: JobNumber }) {
  const main = n.role === "primary";
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1.5 rounded-full px-2.5 py-1 font-label text-xs font-semibold ring-1 ${
        main ? "bg-amber-50 text-amber-900 ring-amber-200" : "bg-surface-subtle text-on-surface ring-border"
      }`}
      title={`${n.display_name} · ${n.number}`}
    >
      <span aria-hidden="true">{main ? "⭐" : "📱"}</span>
      <span className="truncate">{n.display_name}</span>
      <span className="shrink-0 font-normal text-on-surface-muted">{last5(n)}</span>
    </span>
  );
}

function SenderCell({ sender }: { sender: JobSender }) {
  if (sender.kind === "their-number") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-1 font-label text-xs font-semibold text-primary">
        ↩ The number they wrote to
      </span>
    );
  }
  if (sender.kind === "number") {
    return sender.number ? <NumberChip n={sender.number} /> : <span className="text-xs text-on-surface-muted">No Main number yet</span>;
  }
  if (!sender.numbers.length) {
    return <span className="text-xs font-semibold text-amber-700">Paused: no number can send campaigns</span>;
  }
  return (
    <span className="flex flex-wrap items-center gap-1">
      {sender.preferTheirs && <span className="font-label text-xs text-on-surface-muted">Their number first, else</span>}
      {sender.numbers.map((n, i) => (
        <span key={n.id} className="inline-flex items-center gap-1">
          {i > 0 && <span className="text-xs text-on-surface-muted">backup</span>}
          <NumberChip n={n} />
        </span>
      ))}
    </span>
  );
}

/** A short line under a picked job: what happens while the pick can't be used. */
function PickNote({ job, state }: { job: PickJob; state: PickState }) {
  if (!state.picked || !state.why) return null;
  const who = `${state.picked.display_name} ${last5(state.picked)}`;
  const text = state.inUse
    ? `${who} has used today's cap. The rest of a broadcast waits until it has room again.`
    : `${who} can't send right now (${state.why}), so ${job === "reach" ? "Main, then Standby" : "Main"} sends instead.`;
  return <span className="mt-1 block font-body text-xs text-amber-700">{text}</span>;
}

/** "Which number does what". Alerts, OTP codes and Reach have a number dropdown; the rest is shown as it works. */
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
  const groups = numberJobGroups(jobs, numbers);

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
    <div className="rounded-2xl bg-surface p-5 shadow-card ring-1 ring-[#c4c7c7]/15 md:rounded-card md:px-8 md:py-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-lg font-bold text-on-surface">Which number does what</h2>
        <span className="font-body text-xs text-on-surface-muted">Pick a number for alerts, OTP codes and Reach</span>
      </div>
      <div className="mt-3 space-y-4">
        {groups.map((g) => (
          <section key={g.title}>
            <h3 className="font-label text-[11px] font-bold uppercase tracking-wider text-on-surface-muted">{g.title}</h3>
            <ul className="mt-1 divide-y divide-border/70">
              {g.rows.map((r) => {
                const state = r.pick ? pickState(r.pick, jobs, numbers) : null;
                return (
                  <li key={r.job} className="grid grid-cols-1 gap-1.5 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-4">
                    <span className="min-w-0">
                      <span className="block font-body text-sm font-semibold text-on-surface">
                        <span aria-hidden="true">{r.icon}</span> {r.job}
                      </span>
                      <span className="block font-body text-xs text-on-surface-muted">{r.detail}</span>
                      {r.pick && state && <PickNote job={r.pick} state={state} />}
                    </span>
                    <span className="min-w-0 sm:justify-self-end">
                      {r.pick && canManage && onPick ? (
                        <span className="flex flex-col gap-1 sm:items-end">
                          <Select
                            size="sm"
                            aria-label={`Number for ${r.job}`}
                            className="w-full sm:w-64"
                            disabled={saving === r.pick}
                            value={jobs?.picks?.[r.pick] ?? AUTO}
                            onChange={(v) => pick(r.pick as PickJob, v)}
                            options={pickOptions(r.pick, jobs, numbers)}
                          />
                          {r.pick === "reach" && (jobs?.picks?.reach ?? null) === null && (
                            <span className="hidden sm:block"><SenderCell sender={r.sender} /></span>
                          )}
                        </span>
                      ) : (
                        <SenderCell sender={r.sender} />
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
      <p className="mt-3 rounded-xl bg-surface-subtle px-3 py-2 font-body text-xs leading-relaxed text-on-surface-muted">
        A reply always goes from the number the customer wrote to, so it lands in the same chat on their phone. Someone who
        never wrote in gets your Main number. Meta&apos;s daily limit is one for your whole business, shared by every number:
        a backup number only sends when Main can&apos;t. Greyed-out numbers can&apos;t be picked right now; the reason is next to
        each one. If Meta rates Main red, a connected Standby number becomes Main by itself.
      </p>
    </div>
  );
}
