"use client";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { BellOff, Check, Plus, Search, X } from "lucide-react";
import { api, type Lead, type SaidStopList, type SaidStopPerson } from "@/lib/api";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { ConfirmModal } from "@/components/ConfirmModal";
import { MobileRecordCard, MobileRecordHeader, MobileRecordGrid } from "@/components/MobileRecord";
import { cn } from "@/lib/utils";
import { FilterMenu, type FilterMenuOption } from "./FilterMenu";
import { DONT_CALL_LABEL, isDontCallRow } from "@/lib/customersApi";

const TZ = "Asia/Kolkata";

const HOW_OPTIONS: FilterMenuOption[] = [
  { value: "all", label: "All" },
  { value: "stop_reply", label: "Replied STOP" },
  { value: "chat_ai", label: "Said no in chat" },
  { value: "call", label: "Asked on a call" },
  { value: "staff", label: "Added by staff" },
  { value: "dont_call", label: DONT_CALL_LABEL },
  { value: "unknown", label: "Before we tracked how" },
];

const SOURCE_WORDS: Record<string, string> = {
  stop_reply: "replied STOP",
  chat_ai: "said no in chat",
  call: "on a call",
  staff: "added by staff",
  unknown: "other",
};

const SOURCE_ORDER = ["stop_reply", "chat_ai", "call", "staff", "unknown"];

const STOPS_FOR = [
  "Broadcasts and SMS campaigns",
  "Follow-ups and nudges when they go quiet",
  "Auto-messages and scheduled templates",
  "Share product and the form welcome message",
  "Telecaller calls",
];

const STILL_GOES = [
  "The AI agent's reply when they message you first",
  "Payment links and payment messages",
  "A message a team member types in their chat",
];

interface Pill {
  label: string;
  className: string;
}

function maskPhone(phone: string | null): string {
  if (!phone) return "";
  if (phone.length <= 8) return phone;
  return `${phone.slice(0, 5)}•• ••${phone.slice(-3)}`;
}

function labelFor(name: string | null, phone: string | null, fallback: string): string {
  return name?.trim() || maskPhone(phone) || fallback;
}

function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  const yearOf = (d: Date) => new Intl.DateTimeFormat("en-IN", { year: "numeric", timeZone: TZ }).format(d);
  const sameYear = yearOf(date) === yearOf(new Date());
  return date.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
    timeZone: TZ,
  });
}

function truncate(text: string, max = 60): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function matchesHow(p: SaidStopPerson, how: string | undefined): boolean {
  if (how === undefined || how === "all") return true;
  if (how === "dont_call") return isDontCallRow(p);
  if (how === "unknown") return p.source === null && !isDontCallRow(p);
  return p.source === how;
}

function howContent(p: SaidStopPerson): ReactNode {
  // Marked Don't call on a call: messages still go, calls do not.
  if (isDontCallRow(p)) {
    return (
      <>
        {DONT_CALL_LABEL}
        <span className="mt-1 block text-xs text-[#64748b]">Messages still go. Calls do not.</span>
      </>
    );
  }
  switch (p.source) {
    case "stop_reply":
      return <>Replied &quot;STOP&quot;</>;
    case "chat_ai":
      return (
        <>
          Said no in chat
          {p.detail ? (
            <span className="mt-1 block text-xs text-[#64748b]">&quot;{truncate(p.detail)}&quot;</span>
          ) : null}
        </>
      );
    case "call":
      return <>Asked on a call</>;
    case "staff":
      return <>Asked a team member</>;
    default:
      return <span className="text-[#64748b]">Before we tracked how</span>;
  }
}

function wherePill(p: SaidStopPerson): Pill | null {
  if (isDontCallRow(p)) {
    return { label: p.detail ? `Call IQ · ${p.detail}` : "Call IQ", className: "bg-[#fef6ee] text-[#b93815]" };
  }
  switch (p.source) {
    case "stop_reply":
      return { label: p.detail ? `Broadcast · ${p.detail}` : "WhatsApp", className: "bg-slate-100 text-slate-700" };
    case "chat_ai":
      return { label: "Chat · AI agent noticed", className: "bg-[#eef4ff] text-[#3538cd]" };
    case "call":
      return { label: p.detail ? `Call IQ · ${p.detail}` : "Call IQ", className: "bg-[#fef6ee] text-[#b93815]" };
    case "staff":
      return { label: p.detail ? `Added by ${p.detail}` : "Added by staff", className: "bg-slate-100 text-slate-700" };
    default:
      return null;
  }
}

function PillBadge({ pill }: { pill: Pill | null }) {
  if (!pill) return <span className="text-[#64748b]">—</span>;
  return (
    <span
      title={pill.label}
      className={cn("inline-block max-w-full truncate rounded-full px-2.5 py-1 text-xs font-semibold", pill.className)}
    >
      {pill.label}
    </span>
  );
}

function StatCard({
  label,
  value,
  valueClass,
  hint,
}: {
  label: string;
  value: string;
  valueClass?: string;
  hint: string;
}) {
  return (
    <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
      <div className="text-sm font-semibold text-[#64748b]">{label}</div>
      <div className={cn("mt-1 text-[28px] font-bold leading-none text-[#0A1528]", valueClass)}>{value}</div>
      <div className="mt-2 text-xs text-[#64748b]">{hint}</div>
    </div>
  );
}

function RecordField({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <div className={cn("min-w-0 rounded-xl bg-surface-low px-3 py-2.5", className)}>
      <div className="text-xs font-bold uppercase tracking-wider text-on-surface-muted">{label}</div>
      <div className="mt-1 min-w-0 text-sm font-semibold text-on-surface">{children}</div>
    </div>
  );
}

export function SaidStopPanel() {
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("leads.manage");

  const [data, setData] = useState<SaidStopList | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [search, setSearch] = useState("");
  const [how, setHow] = useState<string | undefined>(undefined);

  const [removing, setRemoving] = useState<SaidStopPerson | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);

  const [addOpen, setAddOpen] = useState(false);
  const [addTerm, setAddTerm] = useState("");
  const [addResults, setAddResults] = useState<{ term: string; leads: Lead[] } | null>(null);
  const [addBusyId, setAddBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.saidStop.list());
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Debounced customer search for the Add dialog.
  useEffect(() => {
    const q = addTerm.trim();
    if (!addOpen || q.length < 2) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const res = await api.leads.listPage({ search: q, page: 1, limit: 8 });
        if (!cancelled) setAddResults({ term: q, leads: res.data });
      } catch {
        if (!cancelled) {
          setAddResults({ term: q, leads: [] });
          toast.error("Could not search customers");
        }
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [addOpen, addTerm]);

  // Escape closes the Add dialog.
  useEffect(() => {
    if (!addOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setAddOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [addOpen]);

  function openAdd() {
    setAddTerm("");
    setAddResults(null);
    setAddOpen(true);
  }

  async function removePerson() {
    if (!removing) return;
    const label = labelFor(removing.name, removing.phone, "this person");
    setRemoveBusy(true);
    try {
      await api.saidStop.remove([removing.id]);
      toast.success(`Removed ${label} from Said stop`);
      setRemoving(null);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not remove");
    } finally {
      setRemoveBusy(false);
    }
  }

  async function addPerson(lead: Lead) {
    const label = labelFor(lead.name, lead.phone, "this customer");
    setAddBusyId(lead.id);
    try {
      await api.saidStop.add([lead.id]);
      toast.success(`Added ${label} to Said stop`);
      setAddOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add");
    } finally {
      setAddBusyId(null);
    }
  }

  const term = search.trim().toLowerCase();
  const people = data?.people ?? [];
  const summary = data?.summary;
  const visible = people.filter(
    (p) =>
      matchesHow(p, how) &&
      (term === "" || (p.name ?? "").toLowerCase().includes(term) || (p.phone ?? "").includes(term))
  );
  const filtering = term !== "" || (how !== undefined && how !== "all");

  const weekParts = summary
    ? SOURCE_ORDER.filter((k) => (summary.this_week_by_source[k] ?? 0) > 0).map(
        (k) => `${summary.this_week_by_source[k]} ${SOURCE_WORDS[k]}`
      )
    : [];

  const addQuery = addTerm.trim();
  const addReady = addResults !== null && addResults.term === addQuery;

  return (
    <div className="flex flex-col gap-5 xl:flex-row xl:items-start">
      <div className="flex min-w-0 flex-1 flex-col gap-4">
        {!data && !loadFailed && (
          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-8 text-center text-xs text-[#64748b] shadow-sm">
            Loading…
          </div>
        )}

        {!data && loadFailed && (
          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-8 text-center text-xs text-[#64748b] shadow-sm">
            <p>Could not load the Said stop list.</p>
            <button type="button" onClick={load} className="mt-2 text-xs font-semibold text-primary hover:opacity-70">
              Try again
            </button>
          </div>
        )}

        {summary && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <StatCard
                label="On the list"
                value={String(summary.on_list)}
                hint="people · no offers or calls go to them"
              />
              <StatCard
                label="This week"
                value={summary.this_week > 0 ? `+${summary.this_week}` : "0"}
                valueClass={summary.this_week > 0 ? "text-[#b42318]" : undefined}
                hint={weekParts.length > 0 ? weekParts.join(" · ") : "nobody new this week"}
              />
              <StatCard
                label={`Stop rate · last ${summary.window_days} days`}
                value={summary.stop_rate === null ? "—" : `${summary.stop_rate}%`}
                valueClass={
                  summary.stop_rate === null
                    ? undefined
                    : summary.stop_rate < 3
                      ? "text-[#067647]"
                      : "text-[#b54708]"
                }
                hint={
                  summary.stop_rate === null
                    ? "no broadcasts sent in this time"
                    : `${summary.stopped_in_window} of ${summary.messaged_in_window} people you messaged first · fine below 3%`
                }
              />
            </div>

            <div className="rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
              <div className="flex flex-wrap items-center gap-2 border-b border-[#e2e8f0] p-4">
                <div className="relative min-w-[160px] flex-[1_1_220px]">
                  <label htmlFor="said-stop-search" className="sr-only">
                    Search said stop
                  </label>
                  <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#64748b]" />
                  <input
                    id="said-stop-search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search name or number"
                    className="h-9 w-full rounded-xl border border-[#e2e8f0] bg-white pl-9 pr-3 text-sm text-[#0A1528] placeholder:text-[#94a3b8] focus:outline-none focus:ring-2 focus:ring-primary/20"
                  />
                </div>
                <FilterMenu label="How" options={HOW_OPTIONS} value={how} onChange={setHow} showValue />
                {canManage && (
                  <button
                    type="button"
                    onClick={openAdd}
                    className="ml-auto flex shrink-0 items-center gap-1.5 rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-primary-dark transition-colors"
                  >
                    <Plus size={14} />
                    Add to said stop
                  </button>
                )}
              </div>

              {people.length === 0 && (
                <div className="px-6 py-12 text-center">
                  <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-primary/10 text-primary">
                    <BellOff size={20} />
                  </div>
                  <h3 className="mt-4 font-display text-lg font-bold text-[#0A1528]">Nobody has said stop</h3>
                  <p className="mx-auto mt-1 max-w-md text-sm text-[#64748b]">
                    When someone replies STOP, says no in chat, asks on a call, or a team member adds them, they show
                    here and get no offers or calls.
                  </p>
                </div>
              )}

              {people.length > 0 && visible.length === 0 && (
                <div className="px-6 py-10 text-center text-sm text-[#64748b]">
                  <p>No one matches this search.</p>
                  {filtering && (
                    <button
                      type="button"
                      onClick={() => {
                        setSearch("");
                        setHow(undefined);
                      }}
                      className="mt-2 text-xs font-semibold text-primary hover:opacity-70"
                    >
                      Clear
                    </button>
                  )}
                </div>
              )}

              {visible.length > 0 && (
                <>
                  {/* Desktop table */}
                  <div className="hidden overflow-x-auto md:block">
                    <table className="w-full min-w-[720px]">
                      <thead>
                        <tr className="border-b border-[#f1f5f9]">
                          <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">Name</th>
                          <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">How they said stop</th>
                          <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">Where</th>
                          <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">When</th>
                          <th className="px-4 py-3 text-right text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                            <span className="sr-only">Actions</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {visible.map((p) => {
                          const hasName = Boolean(p.name?.trim());
                          return (
                            <tr key={p.id} className="border-t border-[#f1f5f9] transition-colors hover:bg-[#f8fafc]">
                              <td className="px-4 py-3">
                                <Link
                                  href={`/dashboard/leads/${p.id}`}
                                  className="text-sm font-semibold text-[#0A1528] hover:text-primary"
                                >
                                  {labelFor(p.name, p.phone, "No name")}
                                </Link>
                                {hasName && <div className="mt-0.5 text-xs text-[#64748b]">{maskPhone(p.phone)}</div>}
                              </td>
                              <td className="px-4 py-3 text-sm text-[#334155]">{howContent(p)}</td>
                              <td className="px-4 py-3">
                                <PillBadge pill={wherePill(p)} />
                              </td>
                              <td className="px-4 py-3 text-xs text-[#64748b]">{formatWhen(p.opted_out_at)}</td>
                              <td className="px-4 py-3">
                                {canManage && (
                                  <div className="flex justify-end">
                                    <button
                                      type="button"
                                      onClick={() => setRemoving(p)}
                                      className="rounded-lg border border-[#e2e8f0] bg-white px-3 py-1.5 text-xs font-bold text-[#0A1528] hover:bg-slate-50"
                                    >
                                      Remove
                                    </button>
                                  </div>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {/* Phone cards */}
                  <div className="block space-y-3 p-3 md:hidden">
                    {visible.map((p) => {
                      const hasName = Boolean(p.name?.trim());
                      return (
                        <MobileRecordCard key={p.id}>
                          <MobileRecordHeader
                            title={
                              <Link href={`/dashboard/leads/${p.id}`} className="hover:text-primary">
                                {labelFor(p.name, p.phone, "No name")}
                              </Link>
                            }
                            subtitle={hasName ? maskPhone(p.phone) : undefined}
                          />
                          <MobileRecordGrid>
                            <RecordField label="How they said stop" className="col-span-2">
                              {howContent(p)}
                            </RecordField>
                            <RecordField label="Where">
                              <PillBadge pill={wherePill(p)} />
                            </RecordField>
                            <RecordField label="When">{formatWhen(p.opted_out_at)}</RecordField>
                          </MobileRecordGrid>
                          {canManage && (
                            <div className="mt-4 flex justify-end">
                              <button
                                type="button"
                                onClick={() => setRemoving(p)}
                                className="rounded-lg border border-[#e2e8f0] bg-white px-3 py-1.5 text-xs font-bold text-[#0A1528] hover:bg-slate-50"
                              >
                                Remove
                              </button>
                            </div>
                          )}
                        </MobileRecordCard>
                      );
                    })}
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </div>

      <aside className="flex flex-col gap-3 xl:w-[360px] xl:shrink-0">
        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
          <h2 className="font-display text-[15px] font-bold text-[#0A1528]">What stops for these people</h2>
          <ul className="mt-3 space-y-2 text-sm text-[#334155]">
            {STOPS_FOR.map((item) => (
              <li key={item} className="flex items-start gap-2.5">
                <X size={14} className="mt-0.5 shrink-0 text-[#b42318]" aria-hidden="true" />
                <span>
                  {item}
                  {item === "Telecaller calls" && (
                    <span className="ml-2 inline-block rounded-full bg-[#ecfdf3] px-2 py-0.5 align-middle text-xs font-semibold text-[#067647]">
                      new
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
          <h2 className="font-display text-[15px] font-bold text-[#0A1528]">What still goes</h2>
          <ul className="mt-3 space-y-2 text-sm text-[#334155]">
            {STILL_GOES.map((item) => (
              <li key={item} className="flex items-start gap-2.5">
                <Check size={14} className="mt-0.5 shrink-0 text-[#067647]" aria-hidden="true" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-2xl border border-[#c5ebe5] bg-[#effaf8] p-4 text-xs leading-relaxed text-[#0f3f3a]">
          How people get here: replying <strong>STOP</strong>, <strong>unsubscribe</strong> or{" "}
          <strong lang="ta">ஆர்வம் இல்லை</strong>, a clear no in chat (the AI agent notices), &quot;stop messages&quot; on a
          call, or a team member adding them. Only a team member can <strong>Remove</strong>, and only when the customer
          asks. The AI agent never removes anyone.
        </div>
      </aside>

      {addOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget) setAddOpen(false);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="said-stop-add-title"
            className="w-full max-w-md rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-xl"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 id="said-stop-add-title" className="font-display text-lg font-bold text-[#0A1528]">
                  Add someone to Said stop
                </h2>
                <p className="mt-1 text-xs text-[#64748b]">
                  Use this when a customer asked you to stop, e.g. at the counter or on the phone.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setAddOpen(false)}
                aria-label="Close"
                className="shrink-0 rounded-lg p-1.5 text-[#64748b] hover:bg-slate-50 hover:text-[#0A1528]"
              >
                <X size={16} />
              </button>
            </div>

            <div className="relative mt-4">
              <label htmlFor="said-stop-add-search" className="sr-only">
                Find a customer
              </label>
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#64748b]" />
              <input
                id="said-stop-add-search"
                autoFocus
                value={addTerm}
                onChange={(e) => setAddTerm(e.target.value)}
                placeholder="Search name or number"
                className="h-9 w-full rounded-xl border border-[#e2e8f0] bg-white pl-9 pr-3 text-sm text-[#0A1528] placeholder:text-[#94a3b8] focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>

            <div className="mt-2 max-h-72 overflow-y-auto">
              {addQuery.length < 2 && (
                <p className="py-4 text-center text-xs text-[#64748b]">Type at least 2 letters or numbers.</p>
              )}
              {addQuery.length >= 2 && !addReady && (
                <p className="py-4 text-center text-xs text-[#64748b]">Searching…</p>
              )}
              {addQuery.length >= 2 && addReady && addResults && addResults.leads.length === 0 && (
                <p className="py-4 text-center text-xs text-[#64748b]">No customers found</p>
              )}
              {addQuery.length >= 2 && addReady && addResults && addResults.leads.length > 0 && (
                <ul className="divide-y divide-[#f1f5f9]">
                  {addResults.leads.map((lead) => (
                    <li key={lead.id} className="flex items-center justify-between gap-3 py-2.5">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-[#0A1528]">
                          {labelFor(lead.name, lead.phone, "No name")}
                        </div>
                        {lead.name?.trim() && (
                          <div className="text-xs text-[#64748b]">{maskPhone(lead.phone)}</div>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => addPerson(lead)}
                        disabled={addBusyId !== null}
                        className="shrink-0 rounded-xl bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary-dark disabled:opacity-40"
                      >
                        {addBusyId === lead.id ? "Adding…" : "Add"}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}

      <ConfirmModal
        open={removing !== null}
        onClose={() => setRemoving(null)}
        onConfirm={removePerson}
        title={`Remove ${labelFor(removing?.name ?? null, removing?.phone ?? null, "this person")} from Said stop?`}
        description={
          removing && isDontCallRow(removing)
            ? "Only do this if the customer said calling them is fine now. Calls can reach them after this."
            : "Only do this if the customer asked to hear from you again. Offers, follow-ups and calls can reach them after this."
        }
        tone="danger"
        confirmLabel="Remove"
        loading={removeBusy}
        loadingLabel="Removing…"
      />
    </div>
  );
}
