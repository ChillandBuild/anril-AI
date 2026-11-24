/** Which number does what today, as the senders actually work (read only). */
export type NumberJobs = { default_sender_id: string | null; main_id: string | null; reach_ids: string[] };

export type JobNumber = { id: string; display_name: string; number: string; role: string };

/** Who sends a job: one fixed number, the customer's own chat number, or a rotation. */
export type JobSender =
  | { kind: "number"; number: JobNumber | null }
  | { kind: "their-number" }
  | { kind: "rotation"; numbers: JobNumber[]; preferTheirs?: boolean };

export type JobRow = { icon: string; job: string; detail: string; sender: JobSender };
export type JobGroup = { title: string; rows: JobRow[] };

/**
 * "Which number does what", written from how the sending code works (backend: meta_cloud._creds,
 * outbound_router, routes/leads + media). Nothing here is a setting: change Main to move the
 * fixed-number jobs.
 */
export function numberJobGroups(jobs: NumberJobs | null, numbers: JobNumber[]): JobGroup[] {
  const byId = (id: string | null | undefined) => numbers.find((n) => n.id === id) ?? null;
  const main = byId(jobs?.main_id);
  const sender = byId(jobs?.default_sender_id) ?? main;
  const reach = (jobs?.reach_ids ?? []).map(byId).filter((n): n is JobNumber => !!n);
  // Main first, as the campaign sender picks it
  reach.sort((a, b) => (a.role === "primary" ? -1 : b.role === "primary" ? 1 : 0));
  const fixed: JobSender = { kind: "number", number: sender };

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
        { icon: "📣", job: "Reach campaigns", detail: "Broadcasts and sheet uploads", sender: { kind: "rotation", numbers: reach } },
        { icon: "🔁", job: "Bring-back messages", detail: "Re-engagement for quiet customers", sender: { kind: "rotation", numbers: reach, preferTheirs: true } },
      ],
    },
    {
      title: "Sent by Anril on its own",
      rows: [
        { icon: "🎯", job: "New leads from ads", detail: "Welcome message for Facebook and Instagram forms", sender: fixed },
        { icon: "🛒", job: "IndiaMART and JustDial leads", detail: "First message to a new enquiry", sender: fixed },
        { icon: "⚡", job: "Auto-Messages and follow-ups", detail: "Welcome, reminders, scheduled follow-ups", sender: fixed },
        { icon: "🧾", job: "Bills, orders and bookings", detail: "Bills, order updates, payment reminders, bookings", sender: fixed },
        { icon: "🔐", job: "OTP codes", detail: "Login and verification codes", sender: fixed },
        { icon: "🔔", job: "Alerts to you and staff", detail: "Hot leads, human help, evening summary", sender: fixed },
      ],
    },
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
      <span className="shrink-0 font-normal text-on-surface-muted">{n.number.slice(-5)}</span>
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
          {i > 0 && <span className="text-xs text-on-surface-muted">then</span>}
          <NumberChip n={n} />
        </span>
      ))}
    </span>
  );
}

/** "Which number does what", written from how sending works today. Nothing here is a setting. */
export function NumberJobsPanel({ jobs, numbers }: { jobs: NumberJobs | null; numbers: JobNumber[] }) {
  const groups = numberJobGroups(jobs, numbers);
  const extras = numbers.filter((n) => n.role === "extra");
  return (
    <div className="rounded-2xl bg-surface p-5 shadow-card ring-1 ring-[#c4c7c7]/15 md:rounded-card md:px-8 md:py-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-lg font-bold text-on-surface">Which number does what</h2>
        <span className="font-body text-xs text-on-surface-muted">How Anril sends today</span>
      </div>
      <div className="mt-3 space-y-4">
        {groups.map((g) => (
          <section key={g.title}>
            <h3 className="font-label text-[11px] font-bold uppercase tracking-wider text-on-surface-muted">{g.title}</h3>
            <ul className="mt-1 divide-y divide-border/70">
              {g.rows.map((r) => (
                <li key={r.job} className="grid grid-cols-1 gap-1.5 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-4">
                  <span className="min-w-0">
                    <span className="block font-body text-sm font-semibold text-on-surface">
                      <span aria-hidden="true">{r.icon}</span> {r.job}
                    </span>
                    <span className="block font-body text-xs text-on-surface-muted">{r.detail}</span>
                  </span>
                  <span className="min-w-0 sm:justify-self-end">
                    <SenderCell sender={r.sender} />
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <p className="mt-3 rounded-xl bg-surface-subtle px-3 py-2 font-body text-xs leading-relaxed text-on-surface-muted">
        A reply always goes from the number the customer wrote to, so it lands in the same chat on their phone. Someone who
        never wrote in gets your Main number. Make another number Main to move the jobs under &ldquo;Sent by Anril on its
        own&rdquo;. If Meta rates Main red, a connected Standby number becomes Main by itself.
        {extras.length > 0 && " Extra numbers only reply to people who write to them; they are never used for campaigns."}
      </p>
    </div>
  );
}
