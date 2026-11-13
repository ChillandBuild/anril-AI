"use client";

import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import { ChevronRight, Download, FileText, Layers, RefreshCw, Search, Send } from "lucide-react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { MobileRecordCard, MobileRecordField, MobileRecordGrid, MobileRecordHeader } from "@/components/MobileRecord";
import { CheckTick } from "@/components/ui/controls";
import { Select } from "@/components/ui/Select";
import {
  api,
  type ScheduledBulkResult,
  type ScheduledOverview,
  type ScheduledOverviewBroadcast,
  type ScheduledOverviewStatus,
  type ScheduledOverviewTemplate,
} from "@/lib/api";
import { clockOf, formatSendTime, toIstInputs, untilSend } from "@/lib/schedule-time";
import { cn } from "@/lib/utils";
import { buildCsv, downloadCsv } from "./exportCsv";
import { RescheduleDialog } from "./RescheduleDialog";

const UNDO_MS = 6000;
const POLL_MS = 30_000;
const DAY_MS = 86_400_000;
const PREVIEW_ROWS = 5;

// Same rights the sidebar entry checks: schedule from a chat or Segments, or see and change broadcasts.
const ALLOWED_PERMISSIONS = [
  "leads.manage",
  "conversations.reply",
  "telecalling.dialer",
  "outbound_leads.view",
  "outbound_leads.manage",
];

// One grid for the header and every row, so each column's label and content share a left edge.
// The page fills the dashboard width like Segments; the fr columns share what the fixed ones leave.
const GRID = "grid grid-cols-[36px_minmax(200px,2fr)_minmax(150px,1.4fr)_minmax(150px,1.2fr)_110px_110px_200px] items-center gap-x-2 px-4";

// Same palette as the Segments table, so a lead keeps its avatar colour across pages.
const AVATAR_COLORS = ["#e0457b", "#7c5cdb", "#e07a3f", "#2f9e6e", "#4a90d9", "#d4a23a"];

type Tab = "scheduled" | "sent" | "failed" | "cancelled";
type Ref = { kind: "template" | "broadcast"; id: string };
type ActionSpec = { label: string; tone: "outline" | "danger" | "link"; onClick: () => void; disabled?: boolean };

const TABS: { key: Tab; label: string; hint: string; bar: string; word: string }[] = [
  { key: "scheduled", label: "Waiting", hint: "To be sent", bar: "#0b9396", word: "waiting" },
  { key: "sent", label: "Sent", hint: "Delivered", bar: "#16a34a", word: "sent" },
  { key: "failed", label: "Not sent", hint: "Needs a look", bar: "#ea580c", word: "not sent" },
  { key: "cancelled", label: "Cancelled", hint: "Stopped by you", bar: "#94a3b8", word: "cancelled" },
];

const TONE_CLASS: Record<Tab, string> = {
  scheduled: "bg-[#e8f5fd] text-[#0369a1]",
  sent: "bg-[#ecfdf3] text-[#15803d]",
  failed: "bg-[#fff1ec] text-[#c2410c]",
  cancelled: "bg-[#eef2f6] text-[#475569]",
};

const STATUS_LABEL: Record<ScheduledOverviewStatus, string> = {
  scheduled: "Waiting",
  sending: "Sending now",
  sent: "Sent",
  failed: "Not sent",
  skipped: "Not sent",
  cancelled: "Cancelled",
};

function tabOf(status: ScheduledOverviewStatus): Tab | null {
  if (status === "scheduled" || status === "sending") return "scheduled";
  if (status === "sent") return "sent";
  if (status === "failed" || status === "skipped") return "failed";
  if (status === "cancelled") return "cancelled";
  return null;
}

function toneOf(status: ScheduledOverviewStatus): Tab {
  return tabOf(status) ?? "failed";
}

function refKey(ref: Ref): string {
  return `${ref.kind}:${ref.id}`;
}

function refFromKey(key: string): Ref {
  const at = key.indexOf(":");
  return { kind: key.slice(0, at) as Ref["kind"], id: key.slice(at + 1) };
}

/** Refs the server did not refuse. */
function kept(refs: Ref[], result: ScheduledBulkResult): Ref[] {
  const refused = new Set(result.failed.map((f) => `${f.kind}:${f.id}`));
  return refs.filter((ref) => !refused.has(refKey(ref)));
}

function flip(set: Set<string>, key: string): Set<string> {
  const next = new Set(set);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/** One toast per distinct reason, so a refused batch says why without a toast per row. */
function reportLeftAlone(failed: ScheduledBulkResult["failed"]) {
  const byReason = new Map<string, number>();
  for (const f of failed) byReason.set(f.reason, (byReason.get(f.reason) ?? 0) + 1);
  byReason.forEach((n, reason) => toast.error(`${n} ${n === 1 ? "was" : "were"} left alone: ${reason}`));
}

function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter((w) => /^[A-Za-z]/.test(w));
  if (words.length > 0) return words.slice(0, 2).map((w) => w[0].toUpperCase()).join("");
  return name.replace(/\s/g, "").slice(0, 3);
}

function avatarColor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = ((hash << 5) - hash) + id.charCodeAt(i);
    hash = hash & hash;
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

async function downloadFile(broadcast: ScheduledOverviewBroadcast) {
  try {
    const { url } = await api.scheduledOverview.broadcastFile(broadcast.id);
    window.open(url, "_blank");
  } catch (err) {
    toast.error(messageOf(err, "Couldn't open the file"));
  }
}

function StatusPill({ tone, children }: { tone: Tab; children: ReactNode }) {
  return (
    <span className={cn("inline-flex w-fit items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11.5px] font-bold", TONE_CLASS[tone])}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {children}
    </span>
  );
}

function Avatar({ text, color, size = "md" }: { text: string; color: string; size?: "md" | "sm" }) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full font-bold text-white",
        size === "md" ? "h-9 w-9 text-[11px]" : "h-[30px] w-[30px] text-[10px]",
      )}
      style={{ backgroundColor: color }}
    >
      {text}
    </span>
  );
}

function ActionButton({ action }: { action: ActionSpec }) {
  return (
    <button
      type="button"
      disabled={action.disabled}
      onClick={(e) => {
        e.stopPropagation();
        action.onClick();
      }}
      className={cn(
        "inline-flex h-8 items-center whitespace-nowrap rounded-lg text-xs font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        action.tone === "outline" && "border border-primary px-3 text-primary hover:bg-primary/5",
        action.tone === "danger" && "border border-red-200 px-3 text-red-700 hover:bg-red-50",
        action.tone === "link" && "px-2 text-primary hover:underline",
      )}
    >
      {action.label}
    </button>
  );
}

function ActionRow({ actions }: { actions: ActionSpec[] }) {
  return (
    <div className="flex justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
      {actions.map((action) => (
        <ActionButton key={action.label} action={action} />
      ))}
    </div>
  );
}

function SelectBox({ checked, indeterminate = false, onChange, label }: { checked: boolean; indeterminate?: boolean; onChange: (next: boolean) => void; label: string }) {
  return <CheckTick checked={checked} indeterminate={indeterminate} onChange={onChange} aria-label={label} />;
}

function WhenCell({ sendAt, sub }: { sendAt: Date; sub: string }) {
  return (
    <div className="min-w-0">
      <div className="truncate text-sm font-semibold text-[#0A1528]">{formatSendTime(sendAt)}</div>
      {sub && <div className="truncate text-xs text-[#64748b]">{sub}</div>}
    </div>
  );
}

function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (next: string) => void; options: { value: string; label: string }[] }) {
  return (
    <div className="flex items-center gap-2 text-xs text-[#64748b]">
      <span className="whitespace-nowrap">{label}:</span>
      <Select
        size="sm"
        value={value}
        onChange={onChange}
        aria-label={label}
        className="w-auto min-w-[110px] font-bold"
        options={options}
      />
    </div>
  );
}

export function ScheduledTemplatesClient() {
  const router = useRouter();
  const { role, permissions, loading: authLoading } = useAuthRole();
  const canView = role === "owner" || ALLOWED_PERMISSIONS.some((p) => permissions.includes(p));

  const { data, error, isLoading, isValidating, mutate } = useSWR<ScheduledOverview>(
    canView ? "scheduled-overview" : null,
    () => api.scheduledOverview.get(),
    { refreshInterval: POLL_MS, keepPreviousData: true },
  );

  const [tab, setTab] = useState<Tab>("scheduled");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "broadcasts" | "leads">("all");
  const [byFilter, setByFilter] = useState("all");
  const [whenFilter, setWhenFilter] = useState<"all" | "today" | "tomorrow">("all");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [openBatches, setOpenBatches] = useState<Set<string>>(() => new Set());
  const [showAll, setShowAll] = useState<Set<string>>(() => new Set());
  const [dialog, setDialog] = useState<{ refs: Ref[]; seq: number } | null>(null);
  // One change at a time: the ref blocks a second request before React re-renders, the state disables the buttons.
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);

  const templates = data?.templates ?? [];
  const broadcasts = data?.broadcasts ?? [];
  const canTemplates = data?.can_change_templates ?? false;
  const canBroadcasts = data?.can_change_broadcasts ?? false;
  const canAct = (kind: Ref["kind"]) => (kind === "template" ? canTemplates : canBroadcasts);
  const canSelect = tab === "scheduled";
  const isSelectable = (kind: Ref["kind"], status: ScheduledOverviewStatus) => status === "scheduled" && canAct(kind);

  const now = new Date();
  const todayIst = toIstInputs(now).date;
  const tomorrowIst = toIstInputs(new Date(now.getTime() + DAY_MS)).date;
  const templateById = new Map(templates.map((t) => [t.id, t] as const));
  const broadcastById = new Map(broadcasts.map((b) => [b.id, b] as const));

  // Every message of a batch, whatever its status, for the batch tally.
  const batchAll = new Map<string, ScheduledOverviewTemplate[]>();
  for (const t of templates) {
    if (!t.batch_id) continue;
    const list = batchAll.get(t.batch_id);
    if (list) list.push(t);
    else batchAll.set(t.batch_id, [t]);
  }

  const counts: Record<Tab, number> = { scheduled: 0, sent: 0, failed: 0, cancelled: 0 };
  for (const t of templates) {
    const key = tabOf(t.status);
    if (key) counts[key] += 1;
  }
  for (const b of broadcasts) {
    const key = tabOf(b.status);
    if (key) counts[key] += 1;
  }

  const byOptions = Array.from(new Set([...templates.map((t) => t.created_by_name), ...broadcasts.map((b) => b.created_by_name)]))
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b));
  const search = query.trim().toLowerCase();
  const hasFilters = search !== "" || typeFilter !== "all" || byFilter !== "all" || whenFilter !== "all";

  const matches = (parts: (string | null | undefined)[]) => !search || parts.some((p) => !!p && p.toLowerCase().includes(search));
  const byOk = (name: string) => byFilter === "all" || name === byFilter;
  const sendsOk = (iso: string) => {
    if (whenFilter === "all") return true;
    const day = toIstInputs(new Date(iso)).date;
    return day === (whenFilter === "today" ? todayIst : tomorrowIst);
  };

  const visibleBroadcasts = (typeFilter === "leads"
    ? []
    : broadcasts.filter((b) => tabOf(b.status) === tab && byOk(b.created_by_name) && sendsOk(b.send_at) && matches([b.template_name, b.file_name]))
  ).sort((a, b) => Date.parse(a.send_at) - Date.parse(b.send_at));

  const visibleTemplates = typeFilter === "broadcasts"
    ? []
    : templates.filter((t) => tabOf(t.status) === tab && byOk(t.created_by_name) && sendsOk(t.send_at) && matches([t.lead_name, t.lead_phone, t.template_name]));

  // Messages from one batch become one block; single messages stand alone. Blocks sort by send time.
  type Block =
    | { kind: "batch"; id: string; label: string; rows: ScheduledOverviewTemplate[]; at: number }
    | { kind: "single"; row: ScheduledOverviewTemplate; at: number };
  const batchRows = new Map<string, ScheduledOverviewTemplate[]>();
  const blocks: Block[] = [];
  for (const t of visibleTemplates) {
    if (!t.batch_id) {
      blocks.push({ kind: "single", row: t, at: Date.parse(t.send_at) });
      continue;
    }
    const list = batchRows.get(t.batch_id);
    if (list) list.push(t);
    else batchRows.set(t.batch_id, [t]);
  }
  batchRows.forEach((rows, id) => {
    rows.sort((a, b) => Date.parse(a.send_at) - Date.parse(b.send_at));
    blocks.push({
      kind: "batch",
      id,
      label: rows.find((r) => r.batch_label)?.batch_label || "Leads batch",
      rows,
      at: Math.min(...rows.map((r) => Date.parse(r.send_at))),
    });
  });
  blocks.sort((a, b) => a.at - b.at);
  const batchCount = blocks.filter((b) => b.kind === "batch").length;
  const singleCount = blocks.length - batchCount;

  // Selection: only waiting messages and broadcasts the user may change.
  const selectableKeys = new Set<string>();
  for (const t of templates) if (isSelectable("template", t.status)) selectableKeys.add(refKey({ kind: "template", id: t.id }));
  for (const b of broadcasts) if (isSelectable("broadcast", b.status)) selectableKeys.add(refKey({ kind: "broadcast", id: b.id }));
  // Keys of every selectable row the user can see now. Rows in a collapsed batch count: their batch row is visible.
  const visibleKeys = [
    ...visibleBroadcasts.filter((b) => isSelectable("broadcast", b.status)).map((b) => refKey({ kind: "broadcast", id: b.id })),
    ...visibleTemplates.filter((t) => isSelectable("template", t.status)).map((t) => refKey({ kind: "template", id: t.id })),
  ];
  // Selected ids that are still on screen. Everything counting or acting on the selection uses this, never the raw set.
  const visibleKeySet = new Set(visibleKeys);
  const visibleSelected = new Set(Array.from(selected).filter((k) => visibleKeySet.has(k)));
  const selectedRefs: Ref[] = Array.from(visibleSelected).filter((k) => selectableKeys.has(k)).map(refFromKey);
  const allVisibleSelected = visibleKeys.length > 0 && visibleKeys.every((k) => visibleSelected.has(k));
  const someVisibleSelected = visibleKeys.some((k) => visibleSelected.has(k));

  // Drop hidden ids from the stored selection too, so clearing a filter does not bring them back selected.
  const visibleSig = visibleKeys.join("\n");
  useEffect(() => {
    const keep = new Set(visibleSig.split("\n"));
    setSelected((prev) => {
      const next = new Set(Array.from(prev).filter((k) => keep.has(k)));
      return next.size === prev.size ? prev : next;
    });
  }, [visibleSig]);

  function setKeys(keys: string[], on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const k of keys) {
        if (on) next.add(k);
        else next.delete(k);
      }
      return next;
    });
  }

  function dropFromSelection(refs: Ref[]) {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const ref of refs) next.delete(refKey(ref));
      return next;
    });
  }

  function chooseTab(next: Tab) {
    setTab(next);
    setSelected(new Set());
  }

  // The file holds exactly the rows the table shows: the open tab plus the search and every filter.
  function exportRows() {
    const rows: string[][] = [];
    for (const b of visibleBroadcasts) {
      rows.push([
        b.kind === "drip" ? `Drip broadcast (${b.days} days)` : "Broadcast", b.template_name, "", "", b.template_name,
        formatSendTime(new Date(b.send_at)), b.created_by_name, STATUS_LABEL[b.status], b.error ?? "", String(b.recipients), b.file_name ?? "",
      ]);
    }
    for (const block of blocks) {
      const list = block.kind === "batch" ? block.rows : [block.row];
      for (const t of list) {
        rows.push([
          "Template", t.lead_name || "", t.lead_phone || "", block.kind === "batch" ? block.label : "", t.template_name,
          formatSendTime(new Date(t.send_at)), t.created_by_name, STATUS_LABEL[t.status], t.reason ?? "", "", "",
        ]);
      }
    }
    if (rows.length === 0) {
      toast.error("Nothing to export with these filters.");
      return;
    }
    const header = ["Type", "Name", "Phone", "Batch", "Template", "Sends at (IST)", "Scheduled by", "Status", "Reason", "Recipients", "File"];
    downloadCsv(`scheduled_${tab}_${toIstInputs(new Date()).date}.csv`, buildCsv(header, rows));
    toast.success(`Exported ${rows.length} ${rows.length === 1 ? "row" : "rows"}`);
  }

  function openChat(leadId: string) {
    router.push(`/dashboard/conversations?lead=${leadId}`);
  }

  // Every change goes through the bulk endpoint, one item or many.
  async function runBulk(action: "cancel" | "restore" | "reschedule", refs: Ref[], sendAt?: Date): Promise<ScheduledBulkResult> {
    const result = await api.scheduledOverview.bulk({
      action,
      template_ids: refs.filter((r) => r.kind === "template").map((r) => r.id),
      broadcast_ids: refs.filter((r) => r.kind === "broadcast").map((r) => r.id),
      ...(sendAt ? { send_at: sendAt.toISOString() } : {}),
    });
    await mutate();
    return result;
  }

  // Returns false when another change is still in flight; the caller then does nothing (Undo is ignored).
  function startChange(): boolean {
    if (savingRef.current) return false;
    savingRef.current = true;
    setSaving(true);
    return true;
  }

  function endChange() {
    savingRef.current = false;
    setSaving(false);
  }

  async function restoreRefs(refs: Ref[]) {
    if (!startChange()) return;
    try {
      const result = await runBulk("restore", refs);
      const done = kept(refs, result).length;
      if (done > 0) toast.success(done === 1 ? "Back on the schedule." : `${done} back on the schedule.`);
      reportLeftAlone(result.failed);
    } catch (err) {
      toast.error(messageOf(err, "Couldn't undo that"));
    } finally {
      endChange();
    }
  }

  async function cancelRefs(refs: Ref[]) {
    if (!startChange()) return;
    try {
      const result = await runBulk("cancel", refs);
      const done = kept(refs, result);
      if (done.length > 0) {
        toast(done.length === 1 ? "Cancelled. It will not be sent." : `Cancelled ${done.length} messages. They will not be sent.`, {
          duration: UNDO_MS,
          action: { label: "Undo", onClick: () => void restoreRefs(done) },
        });
      }
      reportLeftAlone(result.failed);
      dropFromSelection(done);
    } catch (err) {
      toast.error(messageOf(err, "Couldn't cancel them"));
    } finally {
      endChange();
    }
  }

  /** Resolves with the reason to show in the dialog, or null once the move went through. */
  async function rescheduleRefs(refs: Ref[], at: Date): Promise<string | null> {
    if (!startChange()) return "Still saving the last change. Try again in a moment.";
    try {
      const result = await runBulk("reschedule", refs, at);
      const done = kept(refs, result);
      if (done.length === 0) {
        const reasons = Array.from(new Set(result.failed.map((f) => f.reason))).join(" ");
        return reasons || "None of them could be moved.";
      }
      toast.success(done.length === 1 ? `Moved to ${formatSendTime(at)} IST.` : `${done.length} messages moved to ${formatSendTime(at)} IST.`);
      reportLeftAlone(result.failed);
      dropFromSelection(done);
      return null;
    } finally {
      endChange();
    }
  }

  function openReschedule(refs: Ref[]) {
    setDialog({ refs, seq: Date.now() });
  }

  function singleInfo(ref: Ref): { name: string; sendAt: Date } | null {
    if (ref.kind === "broadcast") {
      const b = broadcastById.get(ref.id);
      return b ? { name: b.template_name, sendAt: new Date(b.send_at) } : null;
    }
    const t = templateById.get(ref.id);
    return t ? { name: t.lead_name || t.lead_phone || "Lead", sendAt: new Date(t.send_at) } : null;
  }

  const dialogInfo = dialog && dialog.refs.length === 1 ? singleInfo(dialog.refs[0]) : null;
  const dialogCount = dialog?.refs.length ?? 0;
  const dialogBroadcasts = dialog ? dialog.refs.filter((r) => r.kind === "broadcast").length : 0;
  const dialogTitle =
    dialogCount === 1
      ? dialog?.refs[0].kind === "broadcast" ? "Reschedule broadcast" : "Reschedule message"
      : dialogBroadcasts === dialogCount ? `Reschedule ${dialogCount} broadcasts` : `Reschedule ${dialogCount} messages`;
  const dialogSubject = dialogInfo
    ? `${dialogInfo.name} · currently ${formatSendTime(dialogInfo.sendAt)} IST`
    : dialogBroadcasts === dialogCount
      ? "Broadcasts move to the time you pick."
      : dialogBroadcasts === 0
        ? "Every selected message moves to the time you pick."
        : "Broadcasts and messages move to the time you pick.";

  // Action sets. A row only offers what the server will accept for its status.
  function templateActions(t: ScheduledOverviewTemplate): ActionSpec[] {
    const ref: Ref = { kind: "template", id: t.id };
    if (canTemplates && (t.status === "scheduled" || t.status === "sending")) {
      const busy = t.status === "sending";
      return [
        { label: "Reschedule", tone: "outline", disabled: busy, onClick: () => openReschedule([ref]) },
        { label: "Cancel", tone: "danger", disabled: busy || saving, onClick: () => void cancelRefs([ref]) },
      ];
    }
    if (canTemplates && t.status === "cancelled") {
      return [{ label: "Undo cancel", tone: "outline", disabled: saving, onClick: () => void restoreRefs([ref]) }];
    }
    return [{ label: "Open chat", tone: "link", onClick: () => openChat(t.lead_id) }];
  }

  function broadcastActions(b: ScheduledOverviewBroadcast): ActionSpec[] {
    const ref: Ref = { kind: "broadcast", id: b.id };
    if (!canBroadcasts) return [];
    if (b.status === "scheduled" || b.status === "sending") {
      const busy = b.status === "sending";
      return [
        { label: "Reschedule", tone: "outline", disabled: busy, onClick: () => openReschedule([ref]) },
        { label: "Cancel", tone: "danger", disabled: busy || saving, onClick: () => void cancelRefs([ref]) },
      ];
    }
    if (b.status === "cancelled") return [{ label: "Undo cancel", tone: "outline", disabled: saving, onClick: () => void restoreRefs([ref]) }];
    // A broadcast that was not sent can't be moved (the server only moves waiting days); resend it from Outbound Leads.
    return [];
  }

  function batchActions(rows: ScheduledOverviewTemplate[]): ActionSpec[] {
    if (!canTemplates) return [];
    const waiting: Ref[] = rows.filter((r) => r.status === "scheduled").map((r) => ({ kind: "template", id: r.id }));
    const cancelled: Ref[] = rows.filter((r) => r.status === "cancelled").map((r) => ({ kind: "template", id: r.id }));
    if (tab === "scheduled" && waiting.length > 0) {
      return [
        { label: "Reschedule all", tone: "outline", onClick: () => openReschedule(waiting) },
        { label: "Cancel all", tone: "danger", disabled: saving, onClick: () => void cancelRefs(waiting) },
      ];
    }
    if (tab === "cancelled" && cancelled.length > 0) {
      return [{ label: "Undo all", tone: "outline", disabled: saving, onClick: () => void restoreRefs(cancelled) }];
    }
    return [];
  }

  function fileButton(b: ScheduledOverviewBroadcast) {
    if (!b.has_file || !b.file_name) return null;
    return (
      <button
        type="button"
        title={b.file_name}
        onClick={(e) => {
          e.stopPropagation();
          void downloadFile(b);
        }}
        className="mt-1 flex max-w-[220px] items-center gap-1.5 text-xs font-semibold text-[#0369a1] hover:underline"
      >
        <FileText size={13} className="shrink-0" />
        <span className="truncate">{b.file_name}</span>
      </button>
    );
  }

  const tagClass = "inline-block rounded-md px-1.5 py-0.5 text-[10px] font-extrabold uppercase tracking-wide";

  // ---- Desktop rows ----

  function renderBroadcastRow(b: ScheduledOverviewBroadcast) {
    const key = refKey({ kind: "broadcast", id: b.id });
    const sendAt = new Date(b.send_at);
    const waiting = tabOf(b.status) === "scheduled";
    return (
      <div key={key} className={cn(GRID, "border-b border-[#f1f5f9] py-3 transition-colors hover:bg-[#f8fafc]", visibleSelected.has(key) && "bg-primary/5")}>
        <div>
          {canSelect && selectableKeys.has(key) && (
            <SelectBox checked={visibleSelected.has(key)} onChange={(on) => setKeys([key], on)} label={`Select ${b.template_name}`} />
          )}
        </div>
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary">
            <Send size={16} className="text-white" />
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-bold text-[#0A1528]">{b.template_name}</div>
            <div className="mt-0.5 flex min-w-0 items-center gap-2 text-xs text-[#64748b]">
              {b.kind === "drip" ? (
                <span className={cn(tagClass, "bg-[#fff7e6] text-[#d97706]")}>Drip · {b.days} days</span>
              ) : (
                <span className={cn(tagClass, "bg-primary-100 text-primary-dark")}>Broadcast</span>
              )}
              <span className="truncate">{b.recipients.toLocaleString("en-IN")} recipients</span>
            </div>
            {fileButton(b)}
            {b.status === "failed" && b.error && <div className="mt-1 text-xs text-[#c2410c]">{b.error}</div>}
          </div>
        </div>
        <div className="min-w-0 truncate text-xs text-[#64748b]">{b.kind === "drip" ? "Repeats daily" : "Sent once"}</div>
        <WhenCell sendAt={sendAt} sub={b.kind === "drip" ? `then daily at ${clockOf(sendAt)}` : waiting ? untilSend(sendAt, now) : ""} />
        <div className="min-w-0 truncate text-sm text-[#334155]">{b.created_by_name}</div>
        <div className="flex items-center">
          <StatusPill tone={toneOf(b.status)}>{STATUS_LABEL[b.status]}</StatusPill>
        </div>
        <ActionRow actions={broadcastActions(b)} />
      </div>
    );
  }

  function renderTemplateRow(t: ScheduledOverviewTemplate, child: boolean) {
    const key = refKey({ kind: "template", id: t.id });
    const name = t.lead_name || t.lead_phone || "Lead";
    const sendAt = new Date(t.send_at);
    const waiting = tabOf(t.status) === "scheduled";
    return (
      <div
        key={key}
        onClick={() => openChat(t.lead_id)}
        className={cn(
          GRID,
          "cursor-pointer border-b border-[#f1f5f9] transition-colors hover:bg-[#f8fafc]",
          child ? "bg-[#f8fafc] py-2.5" : "py-3",
          visibleSelected.has(key) && "bg-primary/5",
        )}
      >
        <div onClick={(e) => e.stopPropagation()}>
          {canSelect && selectableKeys.has(key) && (
            <SelectBox checked={visibleSelected.has(key)} onChange={(on) => setKeys([key], on)} label={`Select ${name}`} />
          )}
        </div>
        <div className={cn("flex min-w-0 items-center gap-2.5", child && "pl-[30px]")}>
          <Avatar text={initialsOf(name)} color={avatarColor(t.lead_id)} size={child ? "sm" : "md"} />
          <div className="min-w-0">
            <div className="truncate text-sm font-bold text-[#0A1528]">{name}</div>
            {t.lead_name && t.lead_phone && <div className="truncate text-xs text-[#64748b]">{t.lead_phone}</div>}
            {t.reason && <div className="text-xs text-[#c2410c]">{t.reason}</div>}
          </div>
        </div>
        {child ? (
          <div />
        ) : (
          <div className="min-w-0">
            <div className="truncate text-xs font-semibold text-[#0A1528]">{t.template_name}</div>
            <div className="truncate text-xs text-[#64748b]">{t.content}</div>
          </div>
        )}
        <WhenCell sendAt={sendAt} sub={!child && waiting ? untilSend(sendAt, now) : ""} />
        {child ? <div /> : <div className="min-w-0 truncate text-sm text-[#334155]">{t.created_by_name}</div>}
        <div className="flex items-center">
          <StatusPill tone={toneOf(t.status)}>{STATUS_LABEL[t.status]}</StatusPill>
        </div>
        <ActionRow actions={templateActions(t)} />
      </div>
    );
  }

  function renderBatch(id: string, label: string, rows: ScheduledOverviewTemplate[]) {
    const open = openBatches.has(id);
    const everything = batchAll.get(id) ?? rows;
    const expanded = showAll.has(id);
    const shown = expanded ? rows : rows.slice(0, PREVIEW_ROWS);
    const tally = TABS.map((t) => [t.word, everything.filter((r) => tabOf(r.status) === t.key).length] as const)
      .filter(([, n]) => n > 0)
      .map(([word, n]) => `${n} ${word}`)
      .join(", ");
    const times = new Set(rows.map((r) => r.send_at));
    const first = new Date(rows[0].send_at);
    const earliest = new Date(Math.min(...rows.map((r) => Date.parse(r.send_at))));
    const selectKeys = rows.filter((r) => isSelectable("template", r.status)).map((r) => refKey({ kind: "template", id: r.id }));
    const everyKeySelected = selectKeys.length > 0 && selectKeys.every((k) => visibleSelected.has(k));
    const someKeySelected = selectKeys.some((k) => visibleSelected.has(k));
    const senders = Array.from(new Set(rows.map((r) => r.created_by_name))).join(", ");

    return (
      <Fragment key={`batch-${id}`}>
        <div
          onClick={() => setOpenBatches((prev) => flip(prev, id))}
          className={cn(GRID, "cursor-pointer border-b border-[#f1f5f9] py-3 transition-colors hover:bg-[#f8fafc]", everyKeySelected && "bg-primary/5")}
        >
          <div onClick={(e) => e.stopPropagation()}>
            {canSelect && selectKeys.length > 0 && (
              <SelectBox
                checked={everyKeySelected}
                indeterminate={someKeySelected && !everyKeySelected}
                onChange={(on) => setKeys(selectKeys, on)}
                label={`Select all in ${label}`}
              />
            )}
          </div>
          <div className="flex min-w-0 items-center gap-2.5">
            <button
              type="button"
              aria-expanded={open}
              aria-label={`${open ? "Collapse" : "Expand"} ${label}`}
              onClick={(e) => {
                e.stopPropagation();
                setOpenBatches((prev) => flip(prev, id));
              }}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[#64748b] hover:bg-[#e2e8f0]"
            >
              <ChevronRight size={15} className={cn("transition-transform", open && "rotate-90")} />
            </button>
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#b45309]">
              <Layers size={16} className="text-white" />
            </span>
            <div className="min-w-0">
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-sm font-bold text-[#0A1528]">{label}</span>
                <span className={cn(tagClass, "shrink-0 bg-primary-100 text-primary-dark")}>Batch · {everything.length}</span>
              </div>
              <div className="truncate text-xs text-[#64748b]">{tally}</div>
            </div>
          </div>
          <div className="min-w-0 truncate text-xs font-semibold text-[#0A1528]">{rows[0].template_name}</div>
          {times.size === 1 ? (
            <WhenCell sendAt={first} sub={tab === "scheduled" ? untilSend(first, now) : ""} />
          ) : (
            <WhenCell sendAt={earliest} sub={`from ${formatSendTime(earliest)}`} />
          )}
          <div className="min-w-0 truncate text-sm text-[#334155]">{senders}</div>
          <div className="flex items-center">
            <StatusPill tone={tab}>
              {rows.length} {TABS.find((t) => t.key === tab)?.word}
            </StatusPill>
          </div>
          <ActionRow actions={batchActions(rows)} />
        </div>
        {open && shown.map((t) => renderTemplateRow(t, true))}
        {open && rows.length > PREVIEW_ROWS && (
          <div className="border-b border-[#f1f5f9] bg-[#f8fafc] py-2 pl-[90px] pr-4">
            <button
              type="button"
              onClick={() => setShowAll((prev) => flip(prev, id))}
              className="text-xs font-bold text-primary hover:underline"
            >
              {expanded ? "Show fewer" : `Show all ${rows.length} leads`}
            </button>
          </div>
        )}
      </Fragment>
    );
  }

  // ---- Mobile cards ----

  function mobileFooter(selectable: boolean, key: string, label: string, actions: ActionSpec[]) {
    return (
      <div className="mt-4 flex items-center justify-between gap-2" onClick={(e) => e.stopPropagation()}>
        <div>
          {canSelect && selectable && <SelectBox checked={visibleSelected.has(key)} onChange={(on) => setKeys([key], on)} label={`Select ${label}`} />}
        </div>
        <ActionRow actions={actions} />
      </div>
    );
  }

  function renderBroadcastCard(b: ScheduledOverviewBroadcast) {
    const key = refKey({ kind: "broadcast", id: b.id });
    const sendAt = new Date(b.send_at);
    return (
      <MobileRecordCard key={key} className={cn(visibleSelected.has(key) && "border-primary/40 bg-primary/5")}>
        <MobileRecordHeader
          title={b.template_name}
          subtitle={`${b.kind === "drip" ? `Drip · ${b.days} days` : "Broadcast"} · ${b.recipients.toLocaleString("en-IN")} recipients`}
          aside={<StatusPill tone={toneOf(b.status)}>{STATUS_LABEL[b.status]}</StatusPill>}
        />
        {fileButton(b)}
        <MobileRecordGrid>
          <MobileRecordField label="Sends at (IST)" value={formatSendTime(sendAt)} />
          <MobileRecordField label="Scheduled by" value={b.created_by_name} />
        </MobileRecordGrid>
        {mobileFooter(isSelectable("broadcast", b.status), key, b.template_name, broadcastActions(b))}
      </MobileRecordCard>
    );
  }

  function renderTemplateCard(t: ScheduledOverviewTemplate) {
    const key = refKey({ kind: "template", id: t.id });
    const name = t.lead_name || t.lead_phone || "Lead";
    return (
      <MobileRecordCard key={key} onClick={() => openChat(t.lead_id)} className={cn("cursor-pointer", visibleSelected.has(key) && "border-primary/40 bg-primary/5")}>
        <MobileRecordHeader
          title={name}
          subtitle={t.reason ? <span className="text-[#c2410c]">{t.reason}</span> : t.lead_name ? t.lead_phone : null}
          aside={<StatusPill tone={toneOf(t.status)}>{STATUS_LABEL[t.status]}</StatusPill>}
        />
        <MobileRecordGrid>
          <MobileRecordField label="Template" value={t.template_name} />
          <MobileRecordField label="Sends at (IST)" value={formatSendTime(new Date(t.send_at))} />
          <MobileRecordField label="Scheduled by" value={t.created_by_name} />
        </MobileRecordGrid>
        {mobileFooter(isSelectable("template", t.status), key, name, templateActions(t))}
      </MobileRecordCard>
    );
  }

  function renderBatchCard(id: string, label: string, rows: ScheduledOverviewTemplate[]) {
    const open = openBatches.has(id);
    const expanded = showAll.has(id);
    const shown = expanded ? rows : rows.slice(0, PREVIEW_ROWS);
    const everything = batchAll.get(id) ?? rows;
    return (
      <MobileRecordCard key={`batch-${id}`}>
        <div className="flex items-start gap-2.5">
          <button
            type="button"
            aria-expanded={open}
            aria-label={`${open ? "Collapse" : "Expand"} ${label}`}
            onClick={() => setOpenBatches((prev) => flip(prev, id))}
            className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[#64748b] hover:bg-[#e2e8f0]"
          >
            <ChevronRight size={15} className={cn("transition-transform", open && "rotate-90")} />
          </button>
          <div className="min-w-0 flex-1">
            <MobileRecordHeader
              title={label}
              subtitle={<span className={cn(tagClass, "bg-primary-100 text-primary-dark")}>Batch · {everything.length}</span>}
              aside={
                <StatusPill tone={tab}>
                  {rows.length} {TABS.find((t) => t.key === tab)?.word}
                </StatusPill>
              }
            />
          </div>
        </div>
        <MobileRecordGrid>
          <MobileRecordField label="Template" value={rows[0].template_name} />
          <MobileRecordField label="Scheduled by" value={rows[0].created_by_name} />
        </MobileRecordGrid>
        <div className="mt-4 flex flex-wrap justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
          <ActionRow actions={batchActions(rows)} />
        </div>
        {open && (
          <div className="mt-3 divide-y divide-[#f1f5f9] rounded-xl border border-[#f1f5f9]">
            {shown.map((t) => {
              const key = refKey({ kind: "template", id: t.id });
              const name = t.lead_name || t.lead_phone || "Lead";
              return (
                <div key={key} className="flex flex-wrap items-center gap-2 px-3 py-2.5">
                  {canSelect && isSelectable("template", t.status) && (
                    <SelectBox checked={visibleSelected.has(key)} onChange={(on) => setKeys([key], on)} label={`Select ${name}`} />
                  )}
                  <Avatar text={initialsOf(name)} color={avatarColor(t.lead_id)} size="sm" />
                  <button type="button" onClick={() => openChat(t.lead_id)} className="min-w-0 flex-1 text-left">
                    <div className="truncate text-sm font-bold text-[#0A1528]">{name}</div>
                    <div className="truncate text-xs text-[#64748b]">{formatSendTime(new Date(t.send_at))}</div>
                    {t.reason && <div className="text-xs text-[#c2410c]">{t.reason}</div>}
                  </button>
                  <StatusPill tone={toneOf(t.status)}>{STATUS_LABEL[t.status]}</StatusPill>
                  <ActionRow actions={templateActions(t)} />
                </div>
              );
            })}
            {rows.length > PREVIEW_ROWS && (
              <div className="px-3 py-2.5">
                <button type="button" onClick={() => setShowAll((prev) => flip(prev, id))} className="text-xs font-bold text-primary hover:underline">
                  {expanded ? "Show fewer" : `Show all ${rows.length} leads`}
                </button>
              </div>
            )}
          </div>
        )}
      </MobileRecordCard>
    );
  }

  // ---- Page body ----

  const hasRows = visibleBroadcasts.length > 0 || blocks.length > 0;
  const emptyText = hasFilters
    ? "Nothing matches these filters."
    : tab === "scheduled"
      ? "Nothing here."
      : "Nothing has this status yet.";

  let body: ReactNode;
  if (!canView) {
    body = null;
  } else if (isLoading) {
    body = <div className="m-4 h-64 animate-pulse rounded-2xl bg-border-subtle" />;
  } else if (error && !data) {
    body = (
      <div className="px-4 py-12 text-center">
        <p className="text-sm font-semibold text-[#0A1528]">{"Couldn't load scheduled sends."}</p>
        <p className="mt-1 text-xs text-[#64748b]">{messageOf(error, "Check your connection and try again.")}</p>
        <button
          type="button"
          onClick={() => void mutate()}
          className="mt-4 h-9 rounded-xl border border-primary px-4 text-xs font-bold text-primary hover:bg-primary/5"
        >
          Try again
        </button>
      </div>
    );
  } else if (!hasRows) {
    body = (
      <div className="px-4 py-12 text-center text-[#64748b]">
        <p className="text-sm font-semibold text-[#0A1528]">{emptyText}</p>
        {!hasFilters && (
          <p className="mt-1 text-xs">
            {tab === "scheduled"
              ? "Schedule a template from Segments or a broadcast from Outbound Leads and it will show up here."
              : "Nothing has this status yet."}
          </p>
        )}
      </div>
    );
  } else {
    body = (
      <>
        <div className="hidden overflow-x-auto md:block">
          <div className="min-w-[1040px]">
            <div className={cn(GRID, "border-b border-[#f1f5f9] py-3 text-[10px] font-bold uppercase tracking-wider text-[#64748b]")}>
              <div>
                {canSelect && visibleKeys.length > 0 && (
                  <SelectBox
                    checked={allVisibleSelected}
                    indeterminate={someVisibleSelected && !allVisibleSelected}
                    onChange={(on) => setKeys(visibleKeys, on)}
                    label="Select all"
                  />
                )}
              </div>
              <div>Customer or batch</div>
              <div>Template</div>
              <div>Sends at (IST)</div>
              <div>Scheduled by</div>
              <div>Status</div>
              <div className="text-right">Action</div>
            </div>

            {visibleBroadcasts.length > 0 && (
              <>
                <div className="flex items-center gap-2.5 bg-[#f1f5f9] px-4 py-2 text-xs font-extrabold uppercase tracking-wider text-[#64748b]">
                  Broadcasts
                  <span className="text-xs font-semibold normal-case tracking-normal">{visibleBroadcasts.length} from Outbound Leads</span>
                </div>
                {visibleBroadcasts.map((b) => renderBroadcastRow(b))}
              </>
            )}

            {blocks.length > 0 && (
              <>
                <div className="flex items-center gap-2.5 bg-[#f1f5f9] px-4 py-2 text-xs font-extrabold uppercase tracking-wider text-[#64748b]">
                  Batches and single messages
                  <span className="text-xs font-semibold normal-case tracking-normal">
                    {batchCount} batch{batchCount === 1 ? "" : "es"} · {singleCount} single
                  </span>
                </div>
                {blocks.map((block) =>
                  block.kind === "single"
                    ? renderTemplateRow(block.row, false)
                    : renderBatch(block.id, block.label, block.rows),
                )}
              </>
            )}
          </div>
        </div>

        <div className="space-y-3 p-3 md:hidden">
          {visibleBroadcasts.map((b) => renderBroadcastCard(b))}
          {blocks.map((block) =>
            block.kind === "single"
              ? renderTemplateCard(block.row)
              : renderBatchCard(block.id, block.label, block.rows),
          )}
        </div>
      </>
    );
  }

  if (authLoading) {
    return <div className="m-6 min-h-[320px] animate-pulse rounded-2xl bg-border-subtle" />;
  }
  if (!canView) {
    return (
      <div className="py-20 text-center">
        <p className="font-body text-sm text-[#64748b]">You do not have access to Scheduled templates.</p>
      </div>
    );
  }

  return (
    <div className="w-full space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {TABS.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              aria-pressed={active}
              onClick={() => chooseTab(t.key)}
              className={cn(
                "relative flex items-center gap-3 overflow-hidden sm:gap-4 rounded-2xl border bg-white py-4 pl-4 pr-3 sm:pl-5 sm:pr-4 text-left transition-all",
                active ? "border-2 border-primary ring-4 ring-primary/10" : "border-[#e2e8f0] hover:border-slate-300",
              )}
            >
              <span className="absolute bottom-3 left-0 top-3 w-1 rounded-r" style={{ backgroundColor: t.bar }} />
              <span className="min-w-[3ch] font-display text-3xl font-bold text-[#0A1528]">{data ? counts[t.key] : "—"}</span>
              <span className="min-w-0">
                <span className="block text-sm font-bold text-[#0A1528]">{t.label}</span>
                <span className="mt-0.5 block text-xs text-[#64748b]">{t.hint}</span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="overflow-hidden rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-[#e2e8f0] p-4">
          <div className="relative min-w-[200px] flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#64748b]" />
            <input
              type="text"
              placeholder="Search name, number, template or file"
              aria-label="Search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-10 w-full rounded-xl border border-[#e2e8f0] bg-white pl-9 pr-3 text-xs text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>
          <FilterSelect
            label="Type"
            value={typeFilter}
            onChange={(v) => setTypeFilter(v as typeof typeFilter)}
            options={[
              { value: "all", label: "All" },
              { value: "broadcasts", label: "Broadcasts" },
              { value: "leads", label: "From leads" },
            ]}
          />
          <FilterSelect
            label="Scheduled by"
            value={byFilter}
            onChange={setByFilter}
            options={[{ value: "all", label: "All" }, ...byOptions.map((name) => ({ value: name, label: name }))]}
          />
          <FilterSelect
            label="Sends"
            value={whenFilter}
            onChange={(v) => setWhenFilter(v as typeof whenFilter)}
            options={[
              { value: "all", label: "Any time" },
              { value: "today", label: "Today" },
              { value: "tomorrow", label: "Tomorrow" },
            ]}
          />
          <button
            type="button"
            onClick={() => void mutate()}
            disabled={isValidating}
            className="flex h-10 items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3 text-xs font-bold text-[#0A1528] transition-colors hover:bg-[#f8fafc] disabled:opacity-40"
          >
            <RefreshCw size={14} className={cn(isValidating && "animate-spin")} />
            Refresh
          </button>
          <button
            type="button"
            onClick={exportRows}
            className="flex h-10 items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3 text-xs font-bold text-[#0A1528] transition-colors hover:bg-[#f8fafc]"
          >
            <Download size={14} />
            Export
          </button>
        </div>

        {body}
      </div>

      {canSelect && selectedRefs.length > 0 && (
        <div
          role="region"
          aria-label="Selection"
          className="fixed bottom-5 left-1/2 z-30 flex max-w-[calc(100vw-24px)] -translate-x-1/2 items-center gap-3 rounded-2xl bg-[#0A1528] py-2.5 pl-5 pr-3 text-sm text-white shadow-xl"
        >
          <span className="whitespace-nowrap">
            <b className="tabular-nums">{selectedRefs.length}</b> selected
          </span>
          <button
            type="button"
            onClick={() => openReschedule(selectedRefs)}
            className="h-8 rounded-lg bg-primary px-3 text-xs font-bold text-white hover:opacity-90"
          >
            Reschedule
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => void cancelRefs(selectedRefs)}
            className="h-8 rounded-lg border border-white/35 px-3 text-xs font-bold text-white hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => setSelected(new Set())}
            className="h-8 px-2 text-xs font-bold text-white/70 hover:text-white"
          >
            Clear
          </button>
        </div>
      )}

      {dialog && (dialogCount > 1 || dialogInfo) && (
        <RescheduleDialog
          key={dialog.seq}
          title={dialogTitle}
          subject={dialogSubject}
          count={dialogCount}
          currentAt={dialogInfo?.sendAt ?? null}
          onClose={() => setDialog(null)}
          onSubmit={async (at) => {
            try {
              const reason = await rescheduleRefs(dialog.refs, at);
              if (reason === null) setDialog(null);
              return reason;
            } catch (err) {
              return messageOf(err, "Couldn't move them");
            }
          }}
        />
      )}
    </div>
  );
}
