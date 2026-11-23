/** Which number does what today, as the senders actually work (read only). */
export type NumberJobs = { default_sender_id: string | null; main_id: string | null; reach_ids: string[] };

type JobNumber = { id: string; display_name: string; number: string; role: string };

/** "Which number does what", written from how sending works today. Nothing here is a setting. */
export function NumberJobsPanel({ jobs, numbers }: { jobs: NumberJobs | null; numbers: JobNumber[] }) {
  const name = (id: string | null | undefined) => {
    const n = numbers.find((x) => x.id === id);
    return n ? `${n.display_name} (${n.number})` : null;
  };
  const main = name(jobs?.main_id) ?? "your Main number";
  const sender = name(jobs?.default_sender_id) ?? main;
  const reach = (jobs?.reach_ids ?? []).map((id) => numbers.find((x) => x.id === id)).filter(Boolean) as JobNumber[];
  const extras = numbers.filter((n) => n.role === "extra");
  const rows: { icon: string; job: string; who: string }[] = [
    { icon: "💬", job: "AI agent replies and chats", who: "The number the customer wrote to. A reply always goes from the same number." },
    {
      icon: "📣",
      job: "Reach campaigns",
      who: reach.length
        ? `${reach.length > 1 ? `${main} first, then Standby numbers with room left` : `${main} only`}.${extras.length ? " Extra numbers are never used." : ""}`
        : "No number can send campaigns right now (paused or not ready).",
    },
    { icon: "🔐", job: "OTP codes", who: sender },
    { icon: "🧾", job: "Bills and order updates", who: sender },
    { icon: "🔔", job: "Alerts to you and staff", who: sender },
  ];
  return (
    <div className="rounded-2xl bg-surface p-5 shadow-card ring-1 ring-[#c4c7c7]/15 md:rounded-card md:px-8">
      <h2 className="font-display text-lg font-bold text-on-surface">Which number does what</h2>
      <ul className="mt-2 divide-y divide-border/70">
        {rows.map((r) => (
          <li key={r.job} className="grid grid-cols-1 gap-1 py-2.5 sm:grid-cols-[16rem_1fr] sm:gap-4">
            <span className="font-body text-sm font-semibold text-on-surface">{r.icon} {r.job}</span>
            <span className="font-body text-sm text-on-surface-muted">{r.who}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 font-body text-xs text-on-surface-muted">
        If the Main number stops, a Standby number takes over by itself and you get an alert. Set Primary moves OTP codes,
        bills and alerts to that number too.
      </p>
    </div>
  );
}

