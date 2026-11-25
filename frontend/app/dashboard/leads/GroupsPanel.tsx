"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import { Check, Download, FolderPlus, Hand, Megaphone, MessageSquareReply, PhoneForwarded, Plus, RefreshCw, Users, X } from "lucide-react";
import { api, CustomerGroup, GroupRule, Lead } from "@/lib/api";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { ConfirmModal } from "@/components/ConfirmModal";
import { Select } from "@/components/ui/Select";
import { cn } from "@/lib/utils";
import { Pagination, usePagedList } from "@/components/ui/Pagination";
import {
  ADD_CALLER_HREF,
  NO_CALLERS_TEXT,
  callingApi,
  campaignHrefForGroup,
  describeCallingResult,
  followUpHrefForGroup,
} from "@/lib/customersApi";
import { paiseToRupeesText, rupeesToPaise, usedByLabel } from "@/lib/groupRuleMoney";

/** Names the rule editor offers, loaded once by the Customers page. */
export interface RuleChoices {
  callers: { id: string; name: string }[];
  campaigns: { id: string; label: string }[];
  broadcasts: { id: string; label: string }[];
  /** Tags in use (Customers > Tag filter). */
  tags?: string[];
}

type RuleField = "status" | "source" | "added" | "handled" | "reply" | "bought" | "tag" | "spend";

const FIELD_LABELS: Record<RuleField, string> = {
  status: "Status is",
  source: "Came from",
  added: "Added in the",
  handled: "Handled by",
  reply: "Reply window is",
  bought: "Bought",
  tag: "Tagged",
  spend: "Total spent",
};
const FIELD_ORDER: RuleField[] = ["status", "source", "added", "handled", "reply", "bought", "tag", "spend"];

const STATUS_CHOICES = [
  { value: "A", label: "Hot" },
  { value: "B", label: "Warm" },
  { value: "C", label: "Cold" },
  { value: "D", label: "Not interested" },
  { value: "buyers", label: "Buyers" },
];
const SOURCE_CHOICES = [
  { value: "inbound", label: "Inbound (messaged us)" },
  { value: "organic", label: "Organic (no ad)" },
  { value: "meta_ads", label: "Meta Ads" },
  { value: "broadcast", label: "Broadcast" },
];
const ADDED_CHOICES = [1, 7, 30, 60, 90, 180, 365].map((d) => ({
  value: String(d),
  label: d === 1 ? "last 1 day (today)" : `last ${d} days`,
}));
const REPLY_CHOICES = [
  { value: "open", label: "Open (they wrote in 24 hours)" },
  { value: "closed", label: "Closed" },
];
const BOUGHT_CHOICES = [
  { value: "repeat", label: "2 or more times" },
  { value: "quiet", label: "Before, not back in 90 days" },
];

/** Which rule rows a saved rule shows. */
function fieldsOf(rule: GroupRule): RuleField[] {
  const out: RuleField[] = [];
  if (rule.segment || rule.buyer) out.push("status");
  if (rule.source_filter) out.push("source");
  if (rule.added_days) out.push("added");
  if (rule.assigned_to) out.push("handled");
  if (rule.reply_window) out.push("reply");
  if (rule.bought) out.push("bought");
  if (rule.tag) out.push("tag");
  if (rule.spend_min_paise !== undefined || rule.spend_max_paise !== undefined) out.push("spend");
  return out;
}

function withoutField(rule: GroupRule, field: RuleField): GroupRule {
  const next = { ...rule };
  if (field === "status") { delete next.segment; delete next.buyer; }
  if (field === "source") { delete next.source_filter; delete next.broadcast_id; delete next.ad_campaign_id; }
  if (field === "added") delete next.added_days;
  if (field === "handled") delete next.assigned_to;
  if (field === "reply") delete next.reply_window;
  if (field === "bought") delete next.bought;
  if (field === "tag") delete next.tag;
  if (field === "spend") { delete next.spend_min_paise; delete next.spend_max_paise; }
  return next;
}

/** A sensible first value when a rule row is added, so the row is never half-empty. */
function withDefault(rule: GroupRule, field: RuleField, defaultTag?: string): GroupRule {
  switch (field) {
    case "status": return { ...rule, segment: "A" };
    case "source": return { ...rule, source_filter: "broadcast" };
    case "added": return { ...rule, added_days: 30 };
    case "handled": return { ...rule, assigned_to: "unassigned" };
    case "reply": return { ...rule, reply_window: "open" };
    case "bought": return { ...rule, bought: "repeat" };
    case "tag": return { ...rule, tag: defaultTag ?? "" };
    case "spend": return { ...rule, spend_min_paise: 0 };
  }
}

function isRuleValid(rule: GroupRule): boolean {
  if (rule.tag !== undefined && !rule.tag.trim()) return false;
  const { spend_min_paise: lo, spend_max_paise: hi } = rule;
  if (lo !== undefined && hi !== undefined && lo > hi) return false;
  return fieldsOf(rule).length > 0;
}

function RuleEditor({ rule, onChange, choices, disabled, canSeeMoney }: {
  rule: GroupRule;
  onChange: (rule: GroupRule) => void;
  choices: RuleChoices;
  disabled?: boolean;
  /** deals.view: the Total spent rule is offered and shown only with it. */
  canSeeMoney?: boolean;
}) {
  const used = fieldsOf(rule);
  const tagNames = choices.tags ?? [];
  const free = FIELD_ORDER.filter((f) => !used.includes(f) && (f !== "spend" || canSeeMoney) && (f !== "tag" || tagNames.length > 0));
  const [adding, setAdding] = useState(false);
  const handledChoices = [
    { value: "unassigned", label: "Nobody (unassigned)" },
    { value: "ai_agent", label: "AI agent" },
    ...choices.callers.map((c) => ({ value: c.id, label: c.name })),
  ];

  function row(field: RuleField) {
    let control: React.ReactNode = null;
    if (field === "status") {
      control = (
        <Select size="sm" aria-label="Status" disabled={disabled} options={STATUS_CHOICES}
          value={rule.buyer ? "buyers" : rule.segment ?? ""}
          onChange={(v) => {
            const next = withoutField(rule, "status");
            onChange(v === "buyers" ? { ...next, buyer: true } : { ...next, segment: v as GroupRule["segment"] });
          }} />
      );
    } else if (field === "source") {
      const src = rule.source_filter;
      control = (
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <Select size="sm" aria-label="Came from" disabled={disabled} options={SOURCE_CHOICES} value={src ?? ""}
            onChange={(v) => onChange({ ...withoutField(rule, "source"), source_filter: v as GroupRule["source_filter"] })} />
          {src === "broadcast" && (
            <Select size="sm" aria-label="Which broadcast" disabled={disabled} value={rule.broadcast_id ?? ""}
              options={[{ value: "", label: "Any broadcast" }, ...choices.broadcasts.map((b) => ({ value: b.id, label: b.label }))]}
              onChange={(v) => onChange({ ...rule, broadcast_id: v || undefined })} />
          )}
          {src === "meta_ads" && (
            <Select size="sm" aria-label="Which campaign" disabled={disabled} value={rule.ad_campaign_id ?? ""}
              options={[{ value: "", label: "Any campaign" }, ...choices.campaigns.map((c) => ({ value: c.id, label: c.label }))]}
              onChange={(v) => onChange({ ...rule, ad_campaign_id: v || undefined })} />
          )}
        </div>
      );
    } else if (field === "added") {
      control = (
        <Select size="sm" aria-label="Added in" disabled={disabled} options={ADDED_CHOICES} value={String(rule.added_days ?? "")}
          onChange={(v) => onChange({ ...rule, added_days: Number(v) })} />
      );
    } else if (field === "handled") {
      control = (
        <Select size="sm" aria-label="Handled by" disabled={disabled} options={handledChoices} value={rule.assigned_to ?? ""}
          onChange={(v) => onChange({ ...rule, assigned_to: v })} />
      );
    } else if (field === "reply") {
      control = (
        <Select size="sm" aria-label="Reply window" disabled={disabled} options={REPLY_CHOICES} value={rule.reply_window ?? ""}
          onChange={(v) => onChange({ ...rule, reply_window: v as GroupRule["reply_window"] })} />
      );
    } else if (field === "tag") {
      const names = tagNames.some((t) => t.toLowerCase() === (rule.tag ?? "").toLowerCase()) || !rule.tag
        ? tagNames : [...tagNames, rule.tag ?? ""];
      control = (
        <Select size="sm" aria-label="Tag" disabled={disabled} value={rule.tag ?? ""}
          options={names.map((t) => ({ value: t, label: t }))}
          onChange={(v) => onChange({ ...rule, tag: v })} />
      );
    } else if (field === "spend") {
      const setSide = (side: "spend_min_paise" | "spend_max_paise", text: string) => {
        const next = { ...rule, [side]: rupeesToPaise(text) };
        // Both boxes empty keeps the row (min 0 = everyone), so it does not vanish while typing.
        if (next.spend_min_paise === undefined && next.spend_max_paise === undefined) next.spend_min_paise = 0;
        onChange(next);
      };
      const bad = rule.spend_min_paise !== undefined && rule.spend_max_paise !== undefined && rule.spend_min_paise > rule.spend_max_paise;
      control = (
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-center gap-1.5">
            <input type="text" inputMode="decimal" aria-label="Spent at least, in rupees" placeholder="₹ from" disabled={disabled}
              defaultValue={paiseToRupeesText(rule.spend_min_paise)} onChange={(e) => setSide("spend_min_paise", e.target.value)}
              className="h-9 w-full min-w-0 rounded-lg border border-[#cbd5e1] px-2.5 text-sm text-[#0A1528] disabled:bg-slate-50" />
            <span className="text-xs text-[#64748b]">to</span>
            <input type="text" inputMode="decimal" aria-label="Spent at most, in rupees" placeholder="₹ up to" disabled={disabled}
              defaultValue={paiseToRupeesText(rule.spend_max_paise)} onChange={(e) => setSide("spend_max_paise", e.target.value)}
              className="h-9 w-full min-w-0 rounded-lg border border-[#cbd5e1] px-2.5 text-sm text-[#0A1528] disabled:bg-slate-50" />
          </div>
          <span className={cn("text-[11px]", bad ? "font-semibold text-red-600" : "text-[#64748b]")}>
            {bad ? "The first amount must be less than the second." : "Total paid, after refunds. Leave one side empty for no limit."}
          </span>
        </div>
      );
    } else {
      control = (
        <Select size="sm" aria-label="Bought" disabled={disabled} options={BOUGHT_CHOICES} value={rule.bought ?? ""}
          onChange={(v) => onChange({ ...rule, bought: v as GroupRule["bought"] })} />
      );
    }
    return (
      <div key={field} className="flex items-start gap-2">
        <span className="w-[104px] shrink-0 pt-2 text-xs font-semibold text-[#64748b]">{FIELD_LABELS[field]}</span>
        <div className="flex min-w-0 flex-1">{control}</div>
        {!disabled && (
          <button type="button" onClick={() => onChange(withoutField(rule, field))}
            aria-label={`Remove rule: ${FIELD_LABELS[field]}`}
            className="mt-1 shrink-0 rounded-lg p-1.5 text-[#64748b] hover:bg-slate-50 hover:text-[#0A1528]">
            <X size={14} />
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {used.map(row)}
      {!disabled && free.length > 0 && (
        adding ? (
          <div className="flex flex-wrap gap-1.5 rounded-xl border border-dashed border-[#cbd5e1] p-2">
            {free.map((f) => (
              <button key={f} type="button"
                onClick={() => { onChange(withDefault(rule, f, tagNames[0])); setAdding(false); }}
                className="rounded-lg bg-slate-100 px-2.5 py-1.5 text-xs font-semibold text-[#334155] hover:bg-slate-200">
                {FIELD_LABELS[f].replace(/ (is|in the)$/, "")}
              </button>
            ))}
            <button type="button" onClick={() => setAdding(false)} className="px-2 text-xs font-semibold text-[#64748b]">Cancel</button>
          </div>
        ) : (
          <button type="button" onClick={() => setAdding(true)}
            className="flex items-center gap-1 text-xs font-bold text-primary hover:opacity-80">
            <Plus size={13} /> Add a rule
          </button>
        )
      )}
    </div>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
}

function KindPill({ kind }: { kind: CustomerGroup["kind"] }) {
  return kind === "rule" ? (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-[#eef4ff] px-2.5 py-0.5 text-xs font-semibold text-[#3538cd]">
      <RefreshCw size={11} aria-hidden /> Fills itself
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
      <Hand size={11} aria-hidden /> Picked
    </span>
  );
}

type Draft = { kind: "picked" | "rule"; name: string; rule: GroupRule };

export function GroupsPanel({ choices }: { choices: RuleChoices }) {
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("leads.manage");
  const canSeeMoney = role === "owner" || permissions.includes("deals.view") || permissions.includes("deals.manage");

  const [groups, setGroups] = useState<CustomerGroup[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [editRule, setEditRule] = useState<GroupRule | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [deleting, setDeleting] = useState<CustomerGroup | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [preview, setPreview] = useState<{ groupId: string; people: Lead[]; total: number } | null>(null);
  const [downloading, setDownloading] = useState(false);
  const router = useRouter();
  const [confirmCalling, setConfirmCalling] = useState(false);
  const [callingBusy, setCallingBusy] = useState(false);

  const loadGroups = useCallback(async () => {
    try {
      const list = await api.customerGroups.list();
      setGroups(list);
      setLoadFailed(false);
      setSelectedId((current) => (current && list.some((g) => g.id === current) ? current : list[0]?.id ?? null));
    } catch {
      setLoadFailed(true);
    }
  }, []);

  useEffect(() => {
    loadGroups();
  }, [loadGroups]);

  const selected = useMemo(() => groups?.find((g) => g.id === selectedId) ?? null, [groups, selectedId]);

  // The first few people, the same list All people shows for this group.
  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    api.leads
      .listPage({ group_id: selected.id, page: 1, limit: 5 })
      .then((res) => { if (!cancelled) setPreview({ groupId: selected.id, people: res.data, total: res.total }); })
      .catch(() => { if (!cancelled) setPreview({ groupId: selected.id, people: [], total: 0 }); });
    return () => { cancelled = true; };
  }, [selected]);

  function pick(id: string) {
    setSelectedId(id);
    setDraft(null);
    setEditRule(null);
    setRenaming(false);
  }

  async function createGroup() {
    if (!draft) return;
    const name = draft.name.trim();
    if (!name) return;
    setSaving(true);
    try {
      const group = await api.customerGroups.create(name, draft.kind === "rule" ? draft.rule : undefined);
      toast.success(`Created ${group.name}`);
      setDraft(null);
      await loadGroups();
      setSelectedId(group.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create group");
    } finally {
      setSaving(false);
    }
  }

  async function saveRule() {
    if (!selected || !editRule) return;
    setSaving(true);
    try {
      await api.customerGroups.updateRule(selected.id, editRule);
      toast.success("Rules saved. The group updates by itself.");
      setEditRule(null);
      await loadGroups();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the rules");
    } finally {
      setSaving(false);
    }
  }

  async function rename() {
    if (!selected) return;
    const name = renameValue.trim();
    if (!name || name === selected.name) {
      setRenaming(false);
      return;
    }
    try {
      await api.customerGroups.rename(selected.id, name);
      setRenaming(false);
      await loadGroups();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not rename group");
    }
  }

  async function deleteGroup() {
    if (!deleting) return;
    setDeleteBusy(true);
    try {
      await api.customerGroups.remove(deleting.id);
      toast.success(`Deleted ${deleting.name}`);
      setDeleting(null);
      await loadGroups();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete group");
    } finally {
      setDeleteBusy(false);
    }
  }

  async function download() {
    if (!selected) return;
    setDownloading(true);
    try {
      await api.leads.exportLeads({ group_id: selected.id });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not download");
    } finally {
      setDownloading(false);
    }
  }

  async function sendGroupToCalling() {
    if (!selected) return;
    setCallingBusy(true);
    try {
      const result = await callingApi.sendGroup(selected.id);
      setConfirmCalling(false);
      if (result.no_callers) {
        toast.error(NO_CALLERS_TEXT, { action: { label: "Open Team", onClick: () => router.push(ADD_CALLER_HREF) }, duration: 10000 });
      } else {
        toast.success(describeCallingResult(result), { duration: 10000 });
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not send to calling");
    } finally {
      setCallingBusy(false);
    }
  }

  const newButtons = canManage && (
    <div className="flex flex-wrap gap-2">
      <button type="button" onClick={() => { setDraft({ kind: "picked", name: "", rule: {} }); setEditRule(null); }}
        className="flex items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3.5 py-2 text-xs font-bold text-[#0A1528] hover:bg-slate-50">
        <Hand size={14} /> Picked group
      </button>
      <button type="button" onClick={() => { setDraft({ kind: "rule", name: "", rule: { segment: "A" } }); setEditRule(null); }}
        className="flex items-center gap-1.5 rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-primary-dark">
        <RefreshCw size={14} /> Group that fills itself
      </button>
    </div>
  );

  const isEmpty = groups !== null && groups.length === 0;
  const groupPages = usePagedList(groups ?? []);
  const previewForSelected = preview && selected && preview.groupId === selected.id ? preview : null;

  // ---------- right panel ----------
  let panel: React.ReactNode = null;
  if (draft) {
    panel = (
      <form onSubmit={(e) => { e.preventDefault(); createGroup(); }}
        className="space-y-4 rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm">
        <div>
          <h3 className="font-display text-base font-bold text-[#0A1528]">
            {draft.kind === "rule" ? "New group that fills itself" : "New picked group"}
          </h3>
          <p className="mt-1 text-xs text-[#64748b]">
            {draft.kind === "rule"
              ? "People who match these rules join by themselves, and leave when they stop matching."
              : "After creating it, tick people in All people and press Add to group."}
          </p>
        </div>
        <label className="block">
          <span className="text-xs font-semibold text-[#64748b]">Group name</span>
          <input autoFocus value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} maxLength={80}
            placeholder={draft.kind === "rule" ? "e.g. Hot from Diwali broadcast" : "e.g. Expo stall visitors"}
            className="mt-1 w-full rounded-xl border border-[#e2e8f0] px-3 py-2 text-sm text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20" />
        </label>
        {draft.kind === "rule" && (
          <div>
            <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-[#64748b]">People who…</p>
            <RuleEditor rule={draft.rule} onChange={(rule) => setDraft({ ...draft, rule })} choices={choices} canSeeMoney={canSeeMoney} />
          </div>
        )}
        <div className="flex gap-2">
          <button type="submit" disabled={saving || !draft.name.trim() || (draft.kind === "rule" && !isRuleValid(draft.rule))}
            className="rounded-xl bg-primary px-4 py-2 text-xs font-bold text-white disabled:opacity-40">
            {saving ? "Creating…" : "Create group"}
          </button>
          <button type="button" onClick={() => setDraft(null)} className="rounded-xl px-3 py-2 text-xs font-bold text-[#64748b] hover:text-[#0A1528]">
            Cancel
          </button>
        </div>
      </form>
    );
  } else if (selected) {
    const isRule = selected.kind === "rule";
    panel = (
      <div className="space-y-3">
        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm">
          {renaming ? (
            <form onSubmit={(e) => { e.preventDefault(); rename(); }} className="flex items-center gap-1.5">
              <input autoFocus value={renameValue} onChange={(e) => setRenameValue(e.target.value)} maxLength={80}
                onKeyDown={(e) => { if (e.key === "Escape") setRenaming(false); }}
                aria-label="Group name"
                className="min-w-0 flex-1 rounded-lg border border-primary px-2.5 py-1.5 text-sm text-[#0A1528] focus:outline-none focus:ring-1 focus:ring-primary" />
              <button type="submit" aria-label="Save name" className="rounded-lg p-1.5 text-primary hover:bg-primary/5"><Check size={14} /></button>
              <button type="button" onClick={() => setRenaming(false)} aria-label="Cancel rename" className="rounded-lg p-1.5 text-[#64748b] hover:bg-slate-50"><X size={14} /></button>
            </form>
          ) : (
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <h3 className="font-display text-base font-bold text-[#0A1528]">{selected.name}</h3>
              <span className="text-xs text-[#64748b]">{selected.member_count.toLocaleString("en-IN")} people</span>
              <KindPill kind={selected.kind} />
            </div>
          )}
          <p className="mt-1 text-xs text-[#64748b]">
            {selected.made_by ? `Made by ${selected.made_by} · ` : ""}{formatDate(selected.created_at)}
          </p>
          <p className="mt-0.5 text-xs font-semibold text-[#64748b]">{usedByLabel(selected.used_by)}</p>

          {isRule && (
            <div className="mt-4">
              <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-[#64748b]">People who…</p>
              <RuleEditor rule={editRule ?? selected.rule ?? {}} onChange={setEditRule} choices={choices}
                canSeeMoney={canSeeMoney} disabled={!canManage || selected.spend_hidden} />
              {selected.spend_hidden && (
                <p className="mt-2 text-xs text-[#64748b]">
                  This group also has a spend rule. You need access to Orders &amp; payments to see or change the rules.
                </p>
              )}
              {editRule && (
                <div className="mt-3 flex gap-2">
                  <button type="button" onClick={saveRule} disabled={saving || !isRuleValid(editRule)}
                    className="rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-white disabled:opacity-40">
                    {saving ? "Saving…" : "Save rules"}
                  </button>
                  <button type="button" onClick={() => setEditRule(null)} className="rounded-xl px-3 py-2 text-xs font-bold text-[#64748b] hover:text-[#0A1528]">
                    Undo changes
                  </button>
                </div>
              )}
              <p className="mt-3 text-xs leading-relaxed text-[#64748b]">
                Checked again every time it&apos;s opened or used, so new people join and people who stop matching leave by themselves. People can&apos;t be added or removed by hand.
              </p>
            </div>
          )}

          <p className="mt-4 text-[11px] font-bold uppercase tracking-wider text-[#64748b]">In this group</p>
          {!previewForSelected ? (
            <div className="mt-2 space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-4 animate-pulse rounded bg-slate-100" />)}</div>
          ) : previewForSelected.people.length === 0 ? (
            <p className="mt-2 text-xs text-[#64748b]">
              {isRule ? "Nobody matches these rules right now." : "Nobody yet. Tick people in All people and press Add to group."}
            </p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {previewForSelected.people.map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2 text-sm">
                  <Link href={`/dashboard/leads/${p.id}`} className="truncate font-semibold text-[#0A1528] hover:text-primary">
                    {p.name || p.phone || "Unnamed"}
                  </Link>
                  <span className="shrink-0 text-xs text-[#64748b]">
                    {{ A: "Hot", B: "Warm", C: "Cold", D: "Not interested" }[p.segment as "A" | "B" | "C" | "D"] ?? ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {previewForSelected && previewForSelected.total > 0 && (
            <Link href={`/dashboard/leads?tab=people&group_id=${selected.id}`} className="mt-2 inline-block text-xs font-bold text-primary hover:opacity-80">
              See all {previewForSelected.total.toLocaleString("en-IN")} in All people ›
            </Link>
          )}

          {selected.stop_count > 0 && (
            <div className="mt-3 rounded-xl bg-[#fef3f2] px-3 py-2.5 text-xs text-[#912018]">
              {selected.stop_count.toLocaleString("en-IN")} on Said stop. They stay in the group, but no offer or call goes to them.
            </div>
          )}
        </div>

        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm">
          <h3 className="text-sm font-bold text-[#0A1528]">Use this group</h3>
          <div className="mt-3 flex flex-col gap-2">
            <Link href={`/dashboard/leads?tab=people&group_id=${selected.id}`}
              className="flex min-h-10 items-center justify-between gap-2 rounded-xl border border-[#e2e8f0] px-3.5 text-xs font-bold text-[#0A1528] hover:bg-slate-50">
              <span className="flex items-center gap-2"><Users size={14} /> Open in All people</span>
              <span className="font-medium text-[#64748b]">filter</span>
            </Link>
            {role === "owner" && (
            <button type="button" onClick={download} disabled={downloading}
              className="flex min-h-10 items-center justify-between gap-2 rounded-xl border border-[#e2e8f0] px-3.5 text-xs font-bold text-[#0A1528] hover:bg-slate-50 disabled:opacity-50">
              <span className="flex items-center gap-2"><Download size={14} /> {downloading ? "Preparing…" : "Download"}</span>
              <span className="font-medium text-[#64748b]">Excel</span>
            </button>
            )}
            <Link href={campaignHrefForGroup(selected.id)}
              className="flex min-h-10 items-center justify-between gap-2 rounded-xl border border-[#e2e8f0] px-3.5 text-xs font-bold text-[#0A1528] hover:bg-slate-50">
              <span className="flex items-center gap-2"><Megaphone size={14} /> Send a campaign</span>
              <span className="font-medium text-[#556274]">Reach</span>
            </Link>
            {canManage && (
              <button type="button" onClick={() => setConfirmCalling(true)} disabled={selected.member_count === 0}
                className="flex min-h-10 items-center justify-between gap-2 rounded-xl border border-[#e2e8f0] px-3.5 text-xs font-bold text-[#0A1528] hover:bg-slate-50 disabled:opacity-50">
                <span className="flex items-center gap-2"><PhoneForwarded size={14} /> Send to calling</span>
                <span className="font-medium text-[#556274]">Call IQ</span>
              </button>
            )}
            {canManage && (
              <Link href={followUpHrefForGroup(selected.id)}
                className="flex min-h-10 items-center justify-between gap-2 rounded-xl border border-[#e2e8f0] px-3.5 text-xs font-bold text-[#0A1528] hover:bg-slate-50">
                <span className="flex items-center gap-2"><MessageSquareReply size={14} /> Start an auto-message</span>
                <span className="font-medium text-[#556274]">Engage</span>
              </Link>
            )}
          </div>
          {canManage && (
            <div className="mt-4 flex gap-4 text-xs font-bold">
              <button type="button" onClick={() => { setRenaming(true); setRenameValue(selected.name); }} className="text-primary hover:opacity-80">Rename</button>
              <button type="button" onClick={() => setDeleting(selected)} className="text-danger hover:opacity-80">Delete group</button>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs text-[#64748b]">
            Lists of customers: picked by hand, or filled by rules that keep themselves up to date.
          </p>
        </div>
        {!(isEmpty && !draft) && newButtons}
      </div>

      {groups === null && !loadFailed && (
        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-8 text-center text-xs text-[#64748b]">Loading…</div>
      )}

      {loadFailed && (
        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-8 text-center text-xs text-[#64748b]">
          <p>Could not load your groups. Nothing is lost.</p>
          <button type="button" onClick={loadGroups} className="mt-2 text-xs font-semibold text-primary hover:opacity-70">Try again</button>
        </div>
      )}

      {isEmpty && !draft && (
        <div className="rounded-2xl border border-[#e2e8f0] bg-white px-6 py-12 text-center shadow-sm">
          <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-primary/10 text-primary">
            <FolderPlus size={20} />
          </div>
          <h3 className="mt-4 font-display text-lg font-bold text-[#0A1528]">No groups yet</h3>
          <p className="mx-auto mt-1 max-w-md text-sm text-[#64748b]">
            Pick people by hand, or make a group that fills itself, e.g. everyone Hot from your Diwali broadcast.
          </p>
          {canManage && <div className="mt-5 flex justify-center">{newButtons}</div>}
        </div>
      )}

      {groups && (groups.length > 0 || draft) && (
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
          <div className="min-w-0 flex-1 overflow-hidden rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
            {groups.length === 0 ? (
              <p className="p-8 text-center text-xs text-[#64748b]">Your first group will show here.</p>
            ) : (
              <ul className="divide-y divide-[#f1f5f9]">
                <li className="hidden grid-cols-[minmax(0,1fr)_120px_80px_120px] gap-3 bg-[#f8fafc] px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-[#64748b] md:grid">
                  <span>Group</span><span>Type</span><span>People</span><span>Made by</span>
                </li>
                {groupPages.pageItems.map((g) => (
                  <li key={g.id}>
                    <button type="button" onClick={() => pick(g.id)} aria-pressed={g.id === selectedId && !draft}
                      className={cn(
                        "grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 px-4 py-3 text-left transition-colors md:grid-cols-[minmax(0,1fr)_120px_80px_120px]",
                        g.id === selectedId && !draft ? "bg-[#effaf8]" : "hover:bg-[#f8fafc]",
                      )}>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-bold text-[#0A1528]">{g.name}</span>
                        <span className="block truncate text-xs text-[#64748b]">
                          {g.kind === "rule" ? g.rule_text || "Fills itself" : "Picked by hand"}
                        </span>
                        <span className="block truncate text-[11px] font-semibold text-[#94a3b8]">{usedByLabel(g.used_by)}</span>
                      </span>
                      <span className="hidden md:block"><KindPill kind={g.kind} /></span>
                      <span className="text-sm font-semibold text-[#0A1528]">{g.count_unknown ? "?" : g.member_count.toLocaleString("en-IN")}</span>
                      <span className="hidden truncate text-xs text-[#64748b] md:block">
                        {g.made_by ?? "—"} · {formatDate(g.created_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <Pagination page={groupPages.page} total={groupPages.total} onPageChange={groupPages.setPage} noun="groups" />
          </div>
          <div className="xl:w-[400px] xl:shrink-0">{panel}</div>
        </div>
      )}

      <ConfirmModal
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={deleteGroup}
        title="Delete this group?"
        description={`This removes "${deleting?.name ?? ""}". The people in it are not deleted.`}
        tone="danger"
        confirmLabel="Delete group"
        loading={deleteBusy}
        loadingLabel="Deleting…"
      />

      <ConfirmModal
        open={confirmCalling}
        onClose={() => setConfirmCalling(false)}
        onConfirm={sendGroupToCalling}
        title={`Send ${selected?.member_count.toLocaleString("en-IN") ?? 0} people to calling?`}
        description={`Everyone in "${selected?.name ?? "this group"}" goes onto the calling list. People who said stop, already bought, or already have a caller are skipped.`}
        tone="primary"
        confirmLabel="Send to calling"
        loading={callingBusy}
        loadingLabel="Sending…"
      />
    </div>
  );
}
