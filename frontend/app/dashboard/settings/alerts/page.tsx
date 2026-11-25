"use client";
import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { SwitchPill } from "@/components/ui/controls";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import {
  automationsApi,
  groupAlertsByArea,
  HOURS,
  WHO_OPTIONS,
  type AlertRow,
  type AlertsView,
  type WhoChoice,
} from "@/lib/automationsApi";
import { changedAlerts, quietChanged, type AlertEdit, type QuietEdit } from "./alertsDraft";

/** The server marks alerts that can never be switched off (money, the AI agent needs a person, number disconnected). */
type AlertRowView = AlertRow & { locked?: boolean; who_fixed?: boolean };

const HOW_WORDS: Record<string, string> = { bell: "Bell", push: "Phone pop-up", whatsapp: "WhatsApp" };

function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

function QuietTimeCard({ view, edit, canManage, onEdit }: { view: AlertsView["quiet_time"]; edit: QuietEdit; canManage: boolean; onEdit: (next: QuietEdit) => void }) {
  const selectCls =
    "min-h-10 rounded-xl border border-border-subtle bg-white px-2 font-body text-sm text-ink disabled:opacity-60";

  return (
    <section className="card rounded-3xl p-4" aria-labelledby="quiet-time-title">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="quiet-time-title" className="font-label text-base font-bold text-ink">Quiet time</h2>
          <p className="mt-1 font-body text-sm text-[#556274]">
            No phone pop-ups at night, so your team can sleep. The bell inside Anril still fills up.
          </p>
        </div>
        <SwitchPill
          on={edit.on}
          disabled={!canManage}
          aria-label="Quiet time"
          onChange={(next) => onEdit({ ...edit, on: next })}
        />
      </div>

      {view.is_default && (
        <p className="mt-3 rounded-xl border border-border-subtle bg-surface-subtle px-3 py-2 font-body text-sm text-[#556274]">
          This is the default: 9 PM to 9 AM. You have not chosen your own hours yet.
        </p>
      )}

      {edit.on && (
        <div className="mt-3 flex flex-wrap items-center gap-2 font-body text-sm text-ink">
          <label className="flex items-center gap-2">
            From
            <select
              className={selectCls}
              value={edit.start}
              disabled={!canManage}
              onChange={(e) => onEdit({ ...edit, start: Number(e.target.value) })}
              aria-label="Quiet time starts"
            >
              {HOURS.map((h) => <option key={h.value} value={h.value}>{h.label}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2">
            to
            <select
              className={selectCls}
              value={edit.end}
              disabled={!canManage}
              onChange={(e) => onEdit({ ...edit, end: Number(e.target.value) })}
              aria-label="Quiet time ends"
            >
              {HOURS.map((h) => <option key={h.value} value={h.value}>{h.label}</option>)}
            </select>
          </label>
          <span className="text-[#556274]">(India time)</span>
        </div>
      )}

      {edit.on && view.still_comes_through.length > 0 && (
        <div className="mt-3">
          <p className="font-body text-sm font-bold text-ink">Still comes through at night</p>
          <ul className="mt-1 list-disc pl-5 font-body text-sm text-[#556274]">
            {view.still_comes_through.map((l) => <li key={l}>{l}</li>)}
          </ul>
        </div>
      )}
    </section>
  );
}

function AlertLine({ row, canManage, onChange }: { row: AlertRowView; canManage: boolean; onChange: (key: string, edit: AlertEdit) => void }) {
  function run(on: boolean, who?: WhoChoice[]) {
    onChange(row.key, { on, who: who ?? row.who });
  }

  function toggleWho(w: WhoChoice) {
    const has = row.who.includes(w);
    const next = has ? row.who.filter((x) => x !== w) : [...row.who, w];
    if (next.length === 0) {
      toast.error("Pick at least one person to get this alert.");
      return;
    }
    run(row.on, next);
  }

  return (
    <li className="rounded-2xl border border-border-subtle bg-surface-subtle p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-body text-sm font-bold text-ink">{row.label}</p>
          <p className="mt-0.5 font-body text-xs text-[#556274]">
            {row.how.map((h) => HOW_WORDS[h] ?? h).join(" + ")}
            {row.comes_through_in_quiet_time ? " · comes through at night" : ""}
          </p>
          {row.locked && (
            <p className="mt-0.5 font-body text-xs font-semibold text-[#556274]">
              <span aria-hidden>{"🔒 "}</span>Always on. It is too important to switch off.
            </p>
          )}
        </div>
        <SwitchPill on={row.on} disabled={!canManage || !!row.locked} aria-label={row.locked ? `${row.label} (always on)` : row.label} onChange={(next) => run(next)} />
      </div>
      {row.on && (
        <div role="group" aria-label={`Who gets: ${row.label}`} className="mt-2 flex flex-wrap gap-1.5">
          {WHO_OPTIONS.map((o) => {
            const picked = row.who.includes(o.value);
            return (
              <button
                key={o.value}
                type="button"
                aria-pressed={picked}
                disabled={!canManage || !!row.who_fixed}
                onClick={() => toggleWho(o.value)}
                className={`min-h-9 rounded-full border px-3 font-label text-xs font-bold disabled:opacity-60 ${
                  picked ? "border-primary bg-primary text-white" : "border-border-subtle bg-white text-ink hover:border-primary/40"
                }`}
              >
                {o.label}
              </button>
            );
          })}
          {row.who_fixed && (
            <span className="self-center font-body text-xs text-[#556274]">
              {row.key === "number_disconnected" ? "Goes to the owner and anyone who manages numbers." : "Always goes to the person it belongs to."}
            </span>
          )}
        </div>
      )}
    </li>
  );
}

export default function AlertsSettingsPage() {
  const { role, permissions, loading: authLoading } = useAuthRole();
  const canView = role === "owner" || permissions.includes("settings.view") || permissions.includes("settings.manage");
  const canManage = role === "owner" || permissions.includes("settings.manage");

  const { data, error, isLoading, mutate } = useSWR<AlertsView>(canView ? "alerts-view" : null, () => automationsApi.alerts());

  // Changes are held here and sent only when the person presses Save.
  const [edits, setEdits] = useState<Record<string, AlertEdit>>({});
  const [quietEdit, setQuietEdit] = useState<QuietEdit | null>(null);
  const [saving, setSaving] = useState(false);

  const changes = data ? changedAlerts(data.alerts, edits) : [];
  const quietDirty = data ? quietChanged(data.quiet_time, quietEdit) : false;
  const dirty = changes.length > 0 || quietDirty;

  function undo() {
    setEdits({});
    setQuietEdit(null);
  }

  async function saveAll() {
    if (!data || saving) return;
    setSaving(true);
    try {
      for (const c of changes) await automationsApi.setAlert(c.key, c.on, c.who);
      if (quietDirty && quietEdit) await automationsApi.setQuietTime(quietEdit.on, quietEdit.start, quietEdit.end);
      toast.success("Alert settings saved");
    } catch (e) {
      toast.error(errText(e, "Could not save your alert settings."));
    } finally {
      await mutate();
      undo();
      setSaving(false);
    }
  }

  if (authLoading) return null;
  if (!canView) {
    return <p className="font-body text-sm text-[#556274]">You do not have access to alert settings.</p>;
  }

  return (
    <div className="space-y-4 pb-16">
      <p className="font-body text-sm text-[#556274]">Choose what Anril tells you about, and who hears it.</p>

      {isLoading && <div className="card h-24 animate-pulse rounded-3xl bg-border-subtle" />}
      {error && !data && (
        <p role="alert" className="rounded-xl border border-border-subtle bg-surface-subtle px-3 py-2 font-body text-sm text-ink">
          Could not load your alerts. Please refresh.
        </p>
      )}

      {data && (
        <>
          <QuietTimeCard
            view={data.quiet_time}
            edit={quietEdit ?? { on: data.quiet_time.on, start: data.quiet_time.start_hour, end: data.quiet_time.end_hour }}
            canManage={canManage}
            onEdit={setQuietEdit}
          />
          {groupAlertsByArea(data.alerts).map((g) => (
            <section key={g.area} aria-label={g.area} className="space-y-2">
              <h2 className="font-label text-xs font-bold uppercase tracking-wider text-[#556274]">{g.area}</h2>
              <ul className="space-y-2">
                {g.rows.map((r) => (
                  <AlertLine
                    key={r.key}
                    row={{ ...(r as AlertRowView), ...(edits[r.key] ?? {}) }}
                    canManage={canManage}
                    onChange={(key, edit) => setEdits((prev) => ({ ...prev, [key]: edit }))}
                  />
                ))}
              </ul>
            </section>
          ))}
        </>
      )}

      {canManage && dirty && (
        <div className="sticky bottom-[calc(var(--mobile-nav-h)+env(safe-area-inset-bottom,0px)+0.5rem)] z-10 flex items-center justify-between gap-3 rounded-2xl border border-border-subtle bg-white p-3 shadow-lg lg:bottom-3">
          <p className="font-body text-sm font-semibold text-ink">Unsaved changes</p>
          <div className="flex items-center gap-2">
            <button type="button" onClick={undo} disabled={saving} className="btn-secondary min-h-10">Undo</button>
            <button type="button" onClick={() => void saveAll()} disabled={saving} className="btn-primary min-h-11">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
