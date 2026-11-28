"use client";
import { useCallback, useEffect, useState } from "react";
import { Archive, Ban, Download, Info, Loader2, Search, Undo2, X } from "lucide-react";
import { toast } from "sonner";
import { API_URL, getAuthHeaders, Lead, api } from "@/lib/api";
import { cn, formatConvoTime, formatPhone, stripMarkdown } from "@/lib/utils";
import { phoneCell } from "@/lib/csvPhone";
import { CheckTick } from "@/components/ui/controls";
import { Select } from "@/components/ui/Select";
import { ChannelAvatar } from "@/components/channel-avatar";
import { MobileRecordCard, MobileRecordHeader } from "@/components/MobileRecord";
import { channelLabel, downloadCsv, istDateTime, segmentLabel, today, type CsvColumn } from "./exportCsv";

const PAGE = 50;

type FolderView = "archived" | "blocked";
type ArchivedFilters = { q: string; channel: string; segment: string; within: string };

/** Every filter goes to the server, so the count, Load more and Export match what's shown. */
async function fetchView(
  view: FolderView,
  f: ArchivedFilters,
  limit: number,
  offset: number,
): Promise<{ leads: Lead[]; total: number }> {
  const auth = await getAuthHeaders();
  const qs = new URLSearchParams({ view, limit: String(limit), offset: String(offset) });
  if (f.q) qs.set("q", f.q);
  if (f.channel) qs.set("channels", f.channel);
  if (f.segment) qs.set("segments", f.segment);
  if (f.within) qs.set("since", new Date(Date.now() - Number(f.within) * 86_400_000).toISOString());
  const res = await fetch(`${API_URL}/api/v1/conversations?${qs}`, { headers: auth });
  if (!res.ok) throw new Error(`fetch failed: ${res.status}`);
  const data = await res.json();
  return { leads: data.leads ?? [], total: data.total ?? 0 };
}

function shortDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" }) : "";
}

/** The Why chip: the automatic codes in words, else what the teammate typed. */
export function archiveWhy(l: Lead): string {
  if (l.archived_reason === "idle_30d") return "No reply 30 days";
  if (l.archived_reason === "order_delivered") return "Order delivered";
  return l.archived_reason || "";
}

const displayName = (l: Lead) => l.name || formatPhone(l.phone) || (l.tg_username ? `@${l.tg_username}` : "Unknown");

const CHANNEL_OPTIONS = [
  { value: "", label: "All channels" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "instagram", label: "Instagram" },
  { value: "facebook", label: "Facebook" },
  { value: "telegram", label: "Telegram" },
];
const INTEREST_OPTIONS = [
  { value: "", label: "Any interest" },
  { value: "A", label: "Hot" },
  { value: "B", label: "Warm" },
  { value: "C", label: "Cold" },
  { value: "D", label: "Not interested" },
];
const WITHIN_OPTIONS = [
  { value: "", label: "Any time" },
  { value: "7", label: "Last message: 7 days" },
  { value: "30", label: "Last message: 30 days" },
  { value: "90", label: "Last message: 90 days" },
];

const BLOCKED_COLUMNS: CsvColumn<Lead>[] = [
  { header: "Name", value: (l) => l.name },
  { header: "Phone", value: (l) => phoneCell(l.phone) },
  { header: "Channel", value: (l) => channelLabel(l.source) },
  { header: "Blocked at", value: (l) => istDateTime(l.blocked_at) },
  { header: "Blocked by", value: (l) => l.blocked_by_name },
  { header: "Why", value: (l) => l.blocked_reason },
];

/** Every row of a view, page by page (Export takes all matches, not just the loaded page). */
async function fetchAll(view: FolderView, f: ArchivedFilters): Promise<Lead[]> {
  const rows: Lead[] = [];
  for (let offset = 0; offset < 10000; offset += 200) {
    const page = await fetchView(view, f, 200, offset);
    rows.push(...page.leads);
    if (rows.length >= page.total || page.leads.length === 0) break;
  }
  return rows;
}

const COLUMNS: CsvColumn<Lead>[] = [
  { header: "Name", value: (l) => l.name },
  { header: "Phone", value: (l) => phoneCell(l.phone) },
  { header: "Channel", value: (l) => channelLabel(l.source) },
  { header: "Interest", value: (l) => segmentLabel(l.segment) },
  { header: "Last message", value: (l) => l.last_message_content },
  { header: "Last message at", value: (l) => istDateTime((l as Lead & { last_reply_at?: string }).last_reply_at) },
  { header: "Archived at", value: (l) => istDateTime(l.archived_at) },
  {
    header: "Archived by",
    value: (l) =>
      l.archived_reason === "idle_30d" ? "Automatically: no messages for 30 days"
      : l.archived_reason === "order_delivered" ? "Automatically: order delivered"
      : l.archived_by_name,
  },
  { header: "Why", value: (l) => archiveWhy(l) },
];

const EMPTY_TITLE = "Nothing archived";
const EMPTY_TEXT = "Archive a chat from its ⋯ menu in the Inbox to tidy it away.";

/**
 * Chats > Archived & blocked: the archived chat table (search, filters, ticks, Export, Move back)
 * with the Blocked list and the Blocked-vs-Said-stop note beside it.
 */
export function ChatsFolderPanel({
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
  const [channel, setChannel] = useState("");
  const [segment, setSegment] = useState("");
  const [within, setWithin] = useState("");
  const [rows, setRows] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    const h = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(h);
  }, [query]);

  const filters: ArchivedFilters = { q: debounced, channel, segment, within };
  const anyFilter = Boolean(debounced || channel || segment || within);

  const load = useCallback(async () => {
    const f: ArchivedFilters = { q: debounced, channel, segment, within };
    try {
      const page = await fetchView("archived", f, PAGE, 0);
      setRows(page.leads);
      setTotal(page.total);
    } catch {
      toast.error("Couldn't load archived chats");
    } finally {
      setLoading(false);
    }
  }, [debounced, channel, segment, within]);

  useEffect(() => {
    setPicked(new Set());
    void load();
  }, [load]);

  async function loadMore() {
    if (loadingMore || rows.length >= total) return;
    setLoadingMore(true);
    try {
      const page = await fetchView("archived", filters, PAGE, rows.length);
      setRows((prev) => {
        const seen = new Set(prev.map((l) => l.id));
        return [...prev, ...page.leads.filter((l) => !seen.has(l.id))];
      });
      setTotal(page.total);
    } catch {
      toast.error("Couldn't load more");
    } finally {
      setLoadingMore(false);
    }
  }

  // Archive is a toggle on the lead, so calling it again puts the chat back in the Inbox.
  async function putBack(lead: Lead) {
    setBusyId(lead.id);
    try {
      await api.leads.archive(lead.id);
      setRows((prev) => prev.filter((l) => l.id !== lead.id));
      setTotal((t) => Math.max(0, t - 1));
      setPicked((prev) => { const next = new Set(prev); next.delete(lead.id); return next; });
      toast.success(`${displayName(lead)} is back in the Inbox`);
    } catch {
      toast.error("Couldn't move it back");
    } finally {
      setBusyId(null);
    }
  }

  async function exportRows() {
    if (exporting) return;
    setExporting(true);
    try {
      const out = picked.size ? rows.filter((l) => picked.has(l.id)) : await fetchAll("archived", filters); // everything the filters match
      downloadCsv(`archived-chats-${today()}.csv`, out, COLUMNS);
      toast.success("Export downloaded");
    } catch {
      toast.error("Couldn't export. Try again.");
    } finally {
      setExporting(false);
    }
  }

  function clearFilters() {
    setQuery("");
    setChannel("");
    setSegment("");
    setWithin("");
  }

  const allPicked = rows.length > 0 && rows.every((l) => picked.has(l.id));
  const exportCount = picked.size || total;
  const readOnly = canReply ? undefined : "You have read-only access to conversations";

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-background">
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-5 md:px-6">
        <div className="mx-auto grid min-w-0 max-w-[1440px] items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-3">
          <div className="overflow-hidden rounded-2xl border border-border/80 bg-surface shadow-card">
            <div className="flex flex-col gap-3 border-b border-border/70 px-3 py-3 md:px-5">
              <h3 className="flex items-center gap-2 font-display text-[15px] font-bold text-ink">
                <Archive size={15} className="text-ink-muted" /> Archived
                <span className="font-body text-[13px] font-semibold text-ink-muted">{total.toLocaleString("en-IN")}</span>
              </h3>
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative h-8 w-full md:w-[220px]">
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
                <Select size="sm" className="w-full rounded-xl md:w-[132px]" aria-label="Channel" value={channel} onChange={setChannel} options={CHANNEL_OPTIONS} />
                <Select size="sm" className="w-full rounded-xl md:w-[128px]" aria-label="Interest" value={segment} onChange={setSegment} options={INTEREST_OPTIONS} />
                <Select size="sm" className="w-full rounded-xl md:w-[176px]" aria-label="Last message" value={within} onChange={setWithin} options={WITHIN_OPTIONS} />
                {anyFilter && (
                  <button type="button" onClick={clearFilters} className="h-8 rounded-xl px-2.5 text-xs font-semibold text-primary hover:bg-primary-light">
                    Clear
                  </button>
                )}
                <span className="flex-1" />
                {canExport && (
                  <button
                    type="button"
                    onClick={() => void exportRows()}
                    disabled={exporting || exportCount === 0}
                    title={picked.size ? "Download the ticked chats as a spreadsheet" : "Download every archived chat these filters show"}
                    className="inline-flex h-8 items-center gap-1.5 rounded-xl border border-primary-100/80 bg-white px-3 font-label text-xs font-semibold text-gray-700 shadow-xs hover:border-primary-200 hover:bg-primary-50/50 disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    {exporting ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                    {picked.size ? `Export ${picked.size} selected` : `Export ${exportCount.toLocaleString("en-IN")}`}
                  </button>
                )}
              </div>
            </div>

            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[820px] border-collapse">
                <thead>
                  <tr className="border-b border-border/70 bg-slate-50/70 text-left font-heading text-[12px] font-bold uppercase tracking-[0.06em] text-slate-500">
                    {canExport && (
                      <th className="w-10 py-3 pl-5">
                        <CheckTick
                          size="sm"
                          checked={allPicked}
                          indeterminate={!allPicked && rows.some((l) => picked.has(l.id))}
                          onChange={() => setPicked(allPicked ? new Set() : new Set(rows.map((l) => l.id)))}
                          aria-label="Select all shown"
                        />
                      </th>
                    )}
                    <th className={cn("py-3 pr-4", canExport ? "pl-2" : "pl-5")}>Customer</th>
                    <th className="px-4 py-3">Last message</th>
                    <th className="px-4 py-3">Archived</th>
                    <th className="px-4 py-3">Why</th>
                    <th className="px-4 py-3 pr-5 text-right"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr><td colSpan={6} className="px-5 py-10 text-center text-sm text-ink-muted">Loading…</td></tr>
                  ) : rows.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-5 py-12 text-center">
                        <p className="font-display text-[15px] font-semibold text-slate-700">{anyFilter ? "No matches" : EMPTY_TITLE}</p>
                        <p className="mt-1 text-[13px] text-ink-muted">
                          {anyFilter ? "No archived chat matches these filters." : EMPTY_TEXT}
                        </p>
                      </td>
                    </tr>
                  ) : (
                    rows.map((l) => {
                      const lastAt = (l as Lead & { last_reply_at?: string }).last_reply_at;
                      return (
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
                                {l.name && l.phone && <span className="block text-[12px] text-ink-muted">{formatPhone(l.phone)}</span>}
                              </span>
                            </button>
                          </td>
                          <td className="max-w-[280px] px-4 py-3 align-middle">
                            <p className="truncate text-[13px] text-ink-secondary">{stripMarkdown(l.last_message_content) || "No messages"}</p>
                            {lastAt && <p className="text-[12px] text-ink-muted">{formatConvoTime(lastAt)}</p>}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 align-middle text-[13px] text-ink-secondary">
                            {shortDate(l.archived_at)}
                            {l.archived_reason === "idle_30d" || l.archived_reason === "order_delivered" ? (
                              <span className="text-ink-muted"> · by itself</span>
                            ) : l.archived_by_name ? (
                              <span className="text-ink-muted"> · by {l.archived_by_name}</span>
                            ) : null}
                          </td>
                          <td className="max-w-[200px] px-4 py-3 align-middle">
                            {archiveWhy(l) ? (
                              <span className="inline-block max-w-full truncate rounded-full bg-slate-100 px-2.5 py-0.5 text-[12px] font-semibold text-slate-600">
                                {archiveWhy(l)}
                              </span>
                            ) : (
                              <span className="text-[12px] text-ink-muted">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3 pr-5 text-right align-middle">
                            <button
                              type="button"
                              onClick={() => void putBack(l)}
                              disabled={!canReply || busyId === l.id}
                              title={readOnly ?? "Put this chat back in the Inbox"}
                              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-surface px-3 font-label text-[13px] font-bold text-ink hover:border-ink-muted disabled:cursor-not-allowed disabled:opacity-45"
                            >
                              <Undo2 size={13} /> Move back
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
            <div className="space-y-3 p-3 md:hidden">
              {loading ? (
                <p className="px-2 py-8 text-center text-sm text-ink-muted">Loading…</p>
              ) : rows.length === 0 ? (
                <div className="px-2 py-8 text-center">
                  <p className="font-display text-[15px] font-semibold text-slate-700">{anyFilter ? "No matches" : EMPTY_TITLE}</p>
                  <p className="mt-1 text-[13px] text-ink-muted">
                    {anyFilter ? "No archived chat matches these filters." : EMPTY_TEXT}
                  </p>
                </div>
              ) : (
                rows.map((l) => {
                  const why = archiveWhy(l);
                  return (
                    <MobileRecordCard key={l.id} className="p-3">
                      <div className="flex items-start gap-2">
                        {canExport && (
                          <div className="pt-1">
                            <CheckTick
                              size="sm"
                              checked={picked.has(l.id)}
                              onChange={() => setPicked((prev) => { const next = new Set(prev); if (next.has(l.id)) next.delete(l.id); else next.add(l.id); return next; })}
                              aria-label={`Select ${displayName(l)}`}
                            />
                          </div>
                        )}
                        <button type="button" onClick={() => onOpenChat(l.id)} className="flex min-w-0 flex-1 items-start gap-2.5 text-left" title="Open this chat">
                          <ChannelAvatar source={l.source} size={30} />
                          <div className="min-w-0 flex-1">
                            <MobileRecordHeader
                              title={displayName(l)}
                              subtitle={l.name && l.phone ? formatPhone(l.phone) : undefined}
                            />
                          </div>
                        </button>
                      </div>
                      <p className="mt-2 text-[13px] text-on-surface-muted">
                        Archived {shortDate(l.archived_at)}
                        {l.archived_reason === "idle_30d" || l.archived_reason === "order_delivered"
                          ? " · by itself"
                          : l.archived_by_name
                            ? ` · by ${l.archived_by_name}`
                            : ""}
                        {why ? ` · ${why}` : ""}
                      </p>
                      <button
                        type="button"
                        onClick={() => void putBack(l)}
                        disabled={!canReply || busyId === l.id}
                        title={readOnly ?? "Put this chat back in the Inbox"}
                        className="mt-3 inline-flex min-h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-border bg-surface px-3 font-label text-[13px] font-bold text-ink hover:border-ink-muted disabled:cursor-not-allowed disabled:opacity-45"
                      >
                        <Undo2 size={13} /> Move back
                      </button>
                    </MobileRecordCard>
                  );
                })
              )}
            </div>
            {rows.length < total && !loading && (
              <div className="border-t border-border/70 p-3">
                <button
                  onClick={() => void loadMore()}
                  disabled={loadingMore}
                  className="w-full rounded-xl border border-border py-2 text-center text-[13px] font-bold text-primary hover:bg-[#f8fafc] disabled:opacity-50"
                >
                  {loadingMore ? "Loading…" : `Load more (${rows.length} of ${total})`}
                </button>
              </div>
            )}
          </div>

          <div className="flex items-start gap-2 rounded-xl border border-primary/15 bg-primary-light/50 px-4 py-3">
            <Info size={14} className="mt-0.5 shrink-0 text-primary" />
            <p className="text-[13px] leading-relaxed text-ink-secondary">
              Chats move here by themselves after an order is delivered or 30 days with no reply, and go back to the
              Inbox as soon as the customer writes again. They are never deleted: search still finds them, and the
              customer page keeps the full history.
            </p>
          </div>
        </div>
        <aside className="flex min-w-0 flex-col gap-3">
          <BlockedSide canReply={canReply} canExport={canExport} />
          <BlockedVsStop />
        </aside>
        </div>
      </div>
    </div>
  );
}

/** Blocked is not the same as Said stop. Shown under the Blocked list. */
function BlockedVsStop() {
  return (
    <div className="rounded-2xl border border-border/80 bg-surface px-5 py-4 shadow-card">
      <h3 className="font-display text-[14px] font-bold text-ink">Blocked is not the same as Said stop</h3>
      <dl className="mt-2 space-y-2 text-[13px] leading-relaxed text-ink-secondary">
        <div>
          <dt className="inline font-bold text-ink">Blocked:</dt>{" "}
          <dd className="inline">spam or abuse. Nothing goes in or out, and the AI agent stays quiet. Unblock brings them back.</dd>
        </div>
        <div>
          <dt className="inline font-bold text-ink">Said stop:</dt>{" "}
          <dd className="inline">a real customer who wants no offers. Bills, order updates and replies still work; broadcasts and automatic messages skip them.</dd>
        </div>
      </dl>
    </div>
  );
}

const NO_FILTERS: ArchivedFilters = { q: "", channel: "", segment: "", within: "" };

/** The Blocked list beside Archived: newest three, expandable in place to pages of 50, with Unblock. */
function BlockedSide({ canReply, canExport }: { canReply: boolean; canExport: boolean }) {
  const [rows, setRows] = useState<Lead[] | null>(null);
  const [total, setTotal] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchView("blocked", NO_FILTERS, PAGE, 0)
      .then((page) => { if (live) { setRows(page.leads); setTotal(page.total); } })
      .catch(() => { if (live) setRows([]); });
    return () => { live = false; };
  }, []);

  async function unblock(l: Lead) {
    setBusyId(l.id);
    try {
      await api.leads.block(l.id);
      setRows((prev) => (prev ?? []).filter((x) => x.id !== l.id));
      setTotal((t) => Math.max(0, t - 1));
      toast.success(`${displayName(l)} is unblocked`);
    } catch {
      toast.error("Couldn't unblock");
    } finally {
      setBusyId(null);
    }
  }

  async function loadMore() {
    if (loadingMore || !rows) return;
    setLoadingMore(true);
    try {
      const page = await fetchView("blocked", NO_FILTERS, PAGE, rows.length);
      setRows((prev) => {
        const seen = new Set((prev ?? []).map((x) => x.id));
        return [...(prev ?? []), ...page.leads.filter((x) => !seen.has(x.id))];
      });
      setTotal(page.total);
    } catch {
      toast.error("Couldn't load more");
    } finally {
      setLoadingMore(false);
    }
  }

  async function download() {
    if (exporting) return;
    setExporting(true);
    try {
      downloadCsv(`blocked-contacts-${today()}.csv`, await fetchAll("blocked", NO_FILTERS), BLOCKED_COLUMNS);
      toast.success("Download ready");
    } catch {
      toast.error("Couldn't download. Try again.");
    } finally {
      setExporting(false);
    }
  }

  const shown = rows === null ? [] : expanded ? rows : rows.slice(0, 3);
  const hidden = Math.max(0, total - shown.length);

  return (
    <div className="rounded-2xl border border-border/80 bg-surface shadow-card">
      <div className="flex items-start gap-2 border-b border-border/70 px-5 py-3">
        <Ban size={14} className="mt-1 shrink-0 text-red-500" />
        <div className="min-w-0 flex-1">
          <h3 className="font-display text-[15px] font-bold text-ink">Blocked · {total.toLocaleString("en-IN")}</h3>
          <p className="text-[12px] text-ink-muted">no messages in or out, the AI agent stays quiet</p>
        </div>
        {canExport && total > 0 && (
          <button
            type="button"
            onClick={() => void download()}
            disabled={exporting}
            className="inline-flex shrink-0 items-center gap-1 text-[12.5px] font-semibold text-primary hover:underline disabled:opacity-50"
          >
            {exporting ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />} Download
          </button>
        )}
      </div>
      {rows === null ? (
        <p className="px-5 py-4 text-[13px] text-ink-muted">Loading…</p>
      ) : shown.length === 0 ? (
        <p className="px-5 py-4 text-[13px] text-ink-muted">No one is blocked. Block anyone from the ⋯ menu on their chat.</p>
      ) : (
        <ul className={cn(expanded && "max-h-[60vh] overflow-y-auto")}>
          {shown.map((l) => (
            <li key={l.id} className="flex items-center gap-3 border-b border-border-subtle/80 px-5 py-2.5 last:border-b-0">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-bold text-ink">{displayName(l)}</p>
                <p className="truncate text-[12px] text-ink-muted">
                  {[l.blocked_reason, shortDate(l.blocked_at)].filter(Boolean).join(" · ")}
                </p>
              </div>
              <button
                type="button"
                onClick={() => void unblock(l)}
                disabled={!canReply || busyId === l.id}
                className="shrink-0 text-[13px] font-bold text-primary hover:underline disabled:cursor-not-allowed disabled:opacity-45"
              >
                Unblock
              </button>
            </li>
          ))}
        </ul>
      )}
      {expanded && hidden > 0 && (
        <button
          type="button"
          onClick={() => void loadMore()}
          disabled={loadingMore}
          className="w-full border-t border-border/70 px-5 py-2.5 text-left text-[12.5px] font-semibold text-primary hover:bg-primary-50/40 disabled:opacity-50"
        >
          {loadingMore ? "Loading…" : `Load more (${shown.length} of ${total})`}
        </button>
      )}
      {!expanded && hidden > 0 && (
        <button type="button" onClick={() => setExpanded(true)} className="w-full border-t border-border/70 px-5 py-2.5 text-left text-[12.5px] font-semibold text-primary hover:bg-primary-50/40">
          + {hidden.toLocaleString("en-IN")} more
        </button>
      )}
      {expanded && (
        <button type="button" onClick={() => setExpanded(false)} className="w-full border-t border-border/70 px-5 py-2.5 text-left text-[12.5px] font-semibold text-primary hover:bg-primary-50/40">
          Show fewer
        </button>
      )}
    </div>
  );
}
