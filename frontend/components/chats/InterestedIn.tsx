"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Loader2, Pencil, Search } from "lucide-react";
import { toast } from "sonner";
import { api, type CatalogItem } from "@/lib/api";
import { MAX_INTERESTED_ITEMS, toggleItem } from "@/lib/interestedIn";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";

type Picked = { id: string; name: string };

/**
 * Customer card and customer page: the Catalogue items this person is interested in.
 * Anyone who can see the customer sees the list; people with leads.manage can change it.
 */
export function InterestedIn({ leadId }: { leadId: string }) {
  const { role, permissions } = useAuthRole();
  const canEdit = role === "owner" || permissions.includes("leads.manage");
  const [saved, setSaved] = useState<Picked[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState(false);
  const [ids, setIds] = useState<string[]>([]);
  const [items, setItems] = useState<CatalogItem[] | null>(null);
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    setSaved(null);
    setFailed(false);
    setEditing(false);
    api.leads.getInterestedIn(leadId)
      .then((res) => { if (live) setSaved(res.items); })
      .catch(() => { if (live) { setSaved([]); setFailed(true); } });
    return () => { live = false; };
  }, [leadId]);

  function startEdit() {
    setIds((saved ?? []).map((i) => i.id));
    setQuery("");
    setEditing(true);
    if (items === null) {
      api.catalog.listItems().then(setItems).catch(() => setItems([]));
    }
  }

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (items ?? []).filter((i) => !q || i.name.toLowerCase().includes(q));
  }, [items, query]);

  async function save() {
    setSaving(true);
    try {
      const res = await api.leads.setInterestedIn(leadId, ids);
      setSaved(res.items);
      setEditing(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
    } finally {
      setSaving(false);
    }
  }

  if (saved === null) return <p className="text-xs text-[#64748b]">Loading…</p>;

  if (!editing) {
    return (
      <div>
        {saved.length === 0 ? (
          <p className="text-xs text-[#64748b]">{failed ? "Couldn't load this." : "Nothing picked yet"}</p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {saved.map((i) => (
              <span key={i.id} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">{i.name}</span>
            ))}
          </div>
        )}
        {canEdit && (
          <button type="button" onClick={startEdit}
            className="mt-2 inline-flex items-center gap-1 text-xs font-bold text-primary hover:opacity-80">
            <Pencil size={11} aria-hidden /> {saved.length === 0 ? "Pick items" : "Change"}
          </button>
        )}
      </div>
    );
  }

  return (
    <div ref={box} className="rounded-xl border border-[#e2e8f0] bg-white">
      <div className="border-b border-[#f1f5f9] p-2">
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8]" aria-hidden />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search the Catalogue" aria-label="Search the Catalogue"
            className="h-8 w-full rounded-lg border border-[#e2e8f0] pl-8 pr-2 text-xs focus:border-primary focus:outline-none" />
        </div>
      </div>
      <div className="max-h-48 overflow-y-auto">
        {items === null ? (
          <p className="flex items-center gap-2 px-3 py-3 text-xs text-[#64748b]"><Loader2 size={13} className="animate-spin" /> Loading…</p>
        ) : shown.length === 0 ? (
          <p className="px-3 py-3 text-xs text-[#64748b]">{items.length === 0 ? "No items yet. Add them in the Catalogue." : "No item matches that."}</p>
        ) : (
          shown.map((item) => {
            const on = ids.includes(item.id);
            return (
              <button key={item.id} type="button" onClick={() => setIds(toggleItem(ids, item.id))} aria-pressed={on}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-[#f8fafc]">
                <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${on ? "border-primary bg-primary text-white" : "border-[#cbd5e1]"}`}>
                  {on && <Check size={11} aria-hidden />}
                </span>
                <span className="truncate font-semibold text-[#0A1528]">{item.name}</span>
              </button>
            );
          })
        )}
      </div>
      <div className="flex items-center gap-2 border-t border-[#f1f5f9] p-2">
        <button type="button" onClick={save} disabled={saving}
          className="rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white disabled:opacity-40">
          {saving ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={() => setEditing(false)} className="px-2 text-xs font-bold text-[#64748b]">Cancel</button>
        <span className="ml-auto text-[11px] text-[#64748b]">{ids.length} of {MAX_INTERESTED_ITEMS}</span>
      </div>
    </div>
  );
}
