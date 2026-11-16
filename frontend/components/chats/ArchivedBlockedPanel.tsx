"use client";
import { useCallback, useEffect, useState } from "react";
import { Archive, Ban, Download, Info, Loader2, Search, Undo2, X } from "lucide-react";
import { toast } from "sonner";
import { API_URL, getAuthHeaders, Lead, api } from "@/lib/api";
import { cn, formatConvoTime, formatPhone } from "@/lib/utils";
import { CheckTick } from "@/components/ui/controls";
import { ChannelAvatar } from "@/components/channel-avatar";
import { channelLabel, downloadCsv, istDateTime, segmentLabel, today, type CsvColumn } from "./exportCsv";

const PAGE = 50;

async function fetchView(view: "archived" | "blocked", q: string, limit: number, offset: number): Promise<{ leads: Lead[]; total: number }> {
  const auth = await getAuthHeaders();
  const qs = new URLSearchParams({ view, limit: String(limit), offset: String(offset) });
  if (q) qs.set("q", q);
  const res = await fetch(`${API_URL}/api/v1/conversations?${qs}`, { headers: auth });
  if (!res.ok) throw new Error(`fetch failed: ${res.status}`);
  const data = await res.json();
  return { leads: data.leads ?? [], total: data.total ?? 0 };
}

function shortDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" }) : "";
}

const displayName = (l: Lead) => l.name || formatPhone(l.phone) || (l.tg_username ? `@${l.tg_username}` : "Unknown");

const COLUMNS: CsvColumn<Lead>[] = [
  { header: "Name", value: (l) => l.name },
  { header: "Phone", value: (l) => l.phone },
  { header: "Channel", value: (l) => channelLabel(l.source) },
  { header: "Interest", value: (l) => segmentLabel(l.segment) },
  { header: "Last message", value: (l) => l.last_message_content },
  { header: "Last message at", value: (l) => istDateTime((l as Lead & { last_reply_at?: string }).last_reply_at) },
  { header: "Archived at", value: (l) => istDateTime(l.archived_at) },
  { header: "Archived by", value: (l) => (l.archived_reason === "idle_30d" ? "Automatically: no messages for 30 days" : l.archived_by_name) },
];

/**
 * Chats > Archived & blocked: archived chats in a table you can tick and export, and blocked
 * contacts beside it. Both can be put back in one click.
 */
export function ArchivedBlockedPanel({
  onOpenChat,
  canReply,
  canExport,
}: {
  onOpenChat: (leadId: string) => void;
  canReply: boolean;
  canExport: boolean;
}) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [archived, setArchived] = useState<Lead[]>([]);
  const [archivedTotal, setArchivedTotal] = useState(0);
  const [blocked, setBlocked] = useState<Lead[]>([]);
  const [blockedTotal, setBlockedTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    const h = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(h);
  }, [query]);

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([fetchView("archived", debounced, PAGE, 0), fetchView("blocked", "", 200, 0)]);
      setArchived(a.leads);
      setArchivedTotal(a.total);
      setBlocked(b.leads);
      setBlockedTotal(b.total);
    } catch {
      toast.error("Couldn't load archived chats");
    } finally {
      setLoading(false);
    }
  }, [debounced]);

  useEffect(() => {
    setPicked(new Set());
    void load();
  }, [load]);

  async function loadMore() {
    if (loadingMore || archived.length >= archivedTotal) return;
    setLoadingMore(true);
    try {
      const page = await fetchView("archived", debounced, PAGE, archived.length);
      setArchived((prev) => {
        const seen = new Set(prev.map((l) => l.id));
        return [...prev, ...page.leads.filter((l) => !seen.has(l.id))];
      });
      setArchivedTotal(page.total);
    } catch {
      toast.error("Couldn't load more");
    } finally {
      setLoadingMore(false);
    }
  }

  async function moveBack(lead: Lead) {
    setBusyId(lead.id);
    try {
      await api.leads.archive(lead.id); // toggles: archived -> back in the Inbox
      setArchived((prev) => prev.filter((l) => l.id !== lead.id));
      setArchivedTotal((t) => Math.max(0, t - 1));
      setPicked((prev) => { const next = new Set(prev); next.delete(lead.id); return next; });
      toast.success(`${displayName(lead)} is back in the Inbox`);
    } catch {
      toast.error("Couldn't move it back");
    } finally {
      setBusyId(null);
    }
  }

  async function unblock(lead: Lead) {
    setBusyId(lead.id);
    try {
      await api.leads.block(lead.id); // toggles: blocked -> unblocked
      setBlocked((prev) => prev.filter((l) => l.id !== lead.id));
      setBlockedTotal((t) => Math.max(0, t - 1));
      toast.success(`${displayName(lead)} is unblocked`);
    } catch {
      toast.error("Couldn't unblock");
    } finally {
      setBusyId(null);
    }
  }

  async function exportRows() {
    if (exporting) return;
    setExporting(true);
    try {
      let rows: Lead[];
      if (picked.size) rows = archived.filter((l) => picked.has(l.id));
      else {
        // Everything the search matches, not just the loaded page.
        rows = [];
        for (let offset = 0; offset < 10000; offset += 200) {
          const page = await fetchView("archived", debounced, 200, offset);
          rows.push(...page.leads);
          if (rows.length >= page.total || page.leads.length === 0) break;
        }
      }
      downloadCsv(`archived-chats-${today()}.csv`, rows, COLUMNS);
      toast.success("Export downloaded");
    } catch {
      toast.error("Couldn't export. Try again.");
    } finally {
      setExporting(false);
    }
  }

  const allPicked = archived.length > 0 && archived.every((l) => picked.has(l.id));
  const exportCount = picked.size || archivedTotal;
  const readOnly = canReply ? undefined : "You have read-only access to conversations";

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-background">
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          {/* ── Archived ── */}
          <div className="flex min-w-0 flex-col gap-3">
            <div className="overflow-hidden rounded-2xl border border-border/80 bg-surface shadow-card">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-5 py-3">
                <h3 className="flex items-center gap-2 font-display text-[15px] font-bold text-ink">
                  <Archive size={15} className="text-ink-muted" /> Archived
                  <span className="font-body text-[13px] font-semibold text-ink-muted">{archivedTotal.toLocaleString("en-IN")}</span>
                </h3>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="relative h-8 w-[220px]">
                    <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
                    <input
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Search name or phone…"
                      aria-label="Search archived chats"
                      className="h-8 w-full rounded-xl border border-primary-100/80 bg-white pl-8 pr-7 font-body text-xs text-gray-800 outline-none placeholder:text-gray-400 focus:border-[var(--primary-600)] focus:ring-2 focus:ring-[var(--primary-600)]/20"
                    />
                    {query && (
                      <button onClick={() => setQuery("")} aria-label="Clear search" className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                        <X size={12} />
                      </button>
                    )}
                  </div>
                  {canExport && (
                    <button
                      type="button"
                      onClick={() => void exportRows()}
                      disabled={exporting || exportCount === 0}
                      title={picked.size ? "Download the ticked chats as a spreadsheet" : "Download every archived chat this search shows"}
                      className="inline-flex h-8 items-center gap-1.5 rounded-xl border border-primary-100/80 bg-white px-3 font-label text-xs font-semibold text-gray-700 shadow-xs hover:border-primary-200 hover:bg-primary-50/50 disabled:cursor-not-allowed disabled:opacity-45"
                    >
                      {exporting ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                      {picked.size ? `Export ${picked.size} selected` : `Export ${exportCount.toLocaleString("en-IN")}`}
                    </button>
                  )}
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] border-collapse">
                  <thead>
                    <tr className="border-b border-border/70 bg-slate-50/70 text-left font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500">
                      {canExport && (
                        <th className="w-10 py-3 pl-5">
                          <CheckTick
                            size="sm"
                            checked={allPicked}
                            indeterminate={!allPicked && archived.some((l) => picked.has(l.id))}
                            onChange={() => setPicked(allPicked ? new Set() : new Set(archived.map((l) => l.id)))}
                            aria-label="Select all shown"
                          />
                        </th>
                      )}
                      <th className={cn("py-3 pr-4", canExport ? "pl-2" : "pl-5")}>Customer</th>
                      <th className="px-4 py-3">Last message</th>
                      <th className="px-4 py-3">Archived</th>
                      <th className="px-4 py-3 pr-5 text-right"><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {loading ? (
                      <tr><td colSpan={5} className="px-5 py-10 text-center text-sm text-ink-muted">Loading…</td></tr>
                    ) : archived.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="px-5 py-12 text-center">
                          <p className="font-display text-[15px] font-semibold text-slate-700">{debounced ? "No matches" : "Nothing archived"}</p>
                          <p className="mt-1 text-[13px] text-ink-muted">
                            {debounced ? "No archived chat matches that search." : "Archive a chat from its ⋯ menu in the Inbox to tidy it away."}
                          </p>
                        </td>
                      </tr>
                    ) : (
                      archived.map((l) => (
                        <tr key={l.id} className="border-b border-border-subtle/80 last:border-b-0 hover:bg-primary-50/20">
                          {canExport && (
                            <td className="w-10 py-3 pl-5 align-middle">
                              <CheckTick
                                size="sm"
                                checked={picked.has(l.id)}
                                onChange={() => setPicked((prev) => { const next = new Set(prev); if (next.has(l.id)) next.delete(l.id); else next.add(l.id); return next; })}
                                aria-label={`Select ${displayName(l)}`}
                              />
                            </td>
                          )}
                          <td className={cn("py-3 pr-4 align-middle", canExport ? "pl-2" : "pl-5")}>
                            <button type="button" onClick={() => onOpenChat(l.id)} className="flex items-center gap-2.5 text-left" title="Open this chat">
                              <ChannelAvatar source={l.source} size={30} />
                              <span className="min-w-0">
                                <span className="block truncate text-[13px] font-bold text-ink hover:text-primary">{displayName(l)}</span>
                                {l.name && l.phone && <span className="block text-[11.5px] text-ink-muted">{formatPhone(l.phone)}</span>}
                              </span>
                            </button>
                          </td>
                          <td className="max-w-[280px] px-4 py-3 align-middle">
                            <p className="truncate text-[12.5px] text-ink-secondary">{l.last_message_content || "No messages"}</p>
                            {(l as Lead & { last_reply_at?: string }).last_reply_at && (
                              <p className="text-[11px] text-ink-muted">{formatConvoTime((l as Lead & { last_reply_at?: string }).last_reply_at!)}</p>
                            )}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 align-middle text-[12.5px] text-ink-secondary">
                            {shortDate(l.archived_at)}
                            {l.archived_reason === "idle_30d" ? (
                              <span className="text-ink-muted" title="No messages either way for 30 days"> · by itself, 30 days quiet</span>
                            ) : l.archived_by_name ? (
                              <span className="text-ink-muted"> · by {l.archived_by_name}</span>
                            ) : null}
                          </td>
                          <td className="px-4 py-3 pr-5 text-right align-middle">
                            <button
                              type="button"
                              onClick={() => void moveBack(l)}
                              disabled={!canReply || busyId === l.id}
                              title={readOnly ?? "Put this chat back in the Inbox"}
                              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-surface px-3 font-label text-[12px] font-bold text-ink hover:border-ink-muted disabled:cursor-not-allowed disabled:opacity-45"
                            >
                              <Undo2 size={13} /> Move back
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              {archived.length < archivedTotal && !loading && (
                <div className="border-t border-border/70 p-3">
                  <button
                    onClick={() => void loadMore()}
                    disabled={loadingMore}
                    className="w-full rounded-xl border border-border py-2 text-center text-[12px] font-bold text-primary hover:bg-[#f8fafc] disabled:opacity-50"
                  >
                    {loadingMore ? "Loading…" : `Load more (${archived.length} of ${archivedTotal})`}
                  </button>
                </div>
              )}
            </div>

            <div className="flex items-start gap-2 rounded-xl border border-primary/15 bg-primary-light/50 px-4 py-3">
              <Info size={14} className="mt-0.5 shrink-0 text-primary" />
              <p className="text-[12.5px] leading-relaxed text-ink-secondary">
                Chats move here by themselves after 30 days with no messages, and go back to the Inbox as soon as the
                customer writes again. Archived chats are never deleted; Move back puts one in the Inbox now.
              </p>
            </div>
          </div>

          {/* ── Blocked ── */}
          <div className="flex min-w-0 flex-col gap-4">
            <div className="overflow-hidden rounded-2xl border border-border/80 bg-surface shadow-card">
              <div className="border-b border-border/70 px-5 py-3">
                <h3 className="flex items-center gap-2 font-display text-[15px] font-bold text-ink">
                  <Ban size={15} className="text-red-500" /> Blocked
                  <span className="font-body text-[13px] font-semibold text-ink-muted">{blockedTotal.toLocaleString("en-IN")}</span>
                </h3>
                <p className="mt-0.5 text-[12px] text-ink-muted">Hidden from your chats, and the AI agent doesn&apos;t reply to them.</p>
              </div>
              <div className="max-h-[360px] overflow-y-auto">
                {loading ? (
                  <p className="px-5 py-6 text-center text-sm text-ink-muted">Loading…</p>
                ) : blocked.length === 0 ? (
                  <p className="px-5 py-6 text-center text-[13px] text-ink-muted">No one is blocked.</p>
                ) : (
                  blocked.map((l) => (
                    <div key={l.id} className="flex items-center gap-3 border-b border-border-subtle/80 px-5 py-2.5 last:border-b-0">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] font-bold text-ink">{displayName(l)}</p>
                        <p className="truncate text-[11.5px] text-ink-muted">
                          Blocked {shortDate(l.blocked_at)}
                          {l.blocked_by_name ? ` · by ${l.blocked_by_name}` : ""}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => void unblock(l)}
                        disabled={busyId === l.id}
                        className="shrink-0 rounded-lg px-2.5 py-1.5 text-[12.5px] font-bold text-primary hover:bg-primary-light disabled:opacity-45"
                      >
                        Unblock
                      </button>
                    </div>
                  ))
                )}
              </div>
              <p className="border-t border-border/70 px-5 py-2.5 text-[11.5px] text-ink-muted">Block anyone from the ⋯ menu on their chat.</p>
            </div>

            <div className="rounded-2xl border border-border/80 bg-surface px-5 py-4 shadow-card">
              <h3 className="font-display text-[14px] font-bold text-ink">Blocked is not the same as STOP</h3>
              <dl className="mt-2 space-y-2 text-[12.5px] leading-relaxed text-ink-secondary">
                <div>
                  <dt className="inline font-bold text-ink">Blocked:</dt>{" "}
                  <dd className="inline">you hid this contact, for spam or abuse. The AI agent stops replying to them.</dd>
                </div>
                <div>
                  <dt className="inline font-bold text-ink">Said STOP:</dt>{" "}
                  <dd className="inline">the customer asked for no more messages. They stay in your chats with a STOP tag, and broadcasts and automatic messages skip them.</dd>
                </div>
              </dl>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
