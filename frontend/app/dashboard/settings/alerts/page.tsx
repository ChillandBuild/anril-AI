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

/** The server marks alerts that can never be switched off (money, the AI agent needs a person, number disconnected). */
type AlertRowView = AlertRow & { locked?: boolean; who_fixed?: boolean };

const HOW_WORDS: Record<string, string> = { bell: "Bell", push: "Phone pop-up", whatsapp: "WhatsApp" };

function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

function QuietTimeCard({ view, canManage, onSaved }: { view: AlertsView["quiet_time"]; canManage: boolean; onSaved: () => void }) {
  const [busy, setBusy] = useState(false);

  async function save(on: boolean, start: number, end: number) {
    setBusy(true);
    try {
      await automationsApi.setQuietTime(on, start, end);
      onSaved();
    } catch (e) {
      toast.error(errText(e, "Could not save quiet time."));
    } finally {
      setBusy(false);
    }
  }

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
          on={view.on}
          disabled={!canManage}
          loading={busy}
          aria-label="Quiet time"
          onChange={(next) => save(next, view.start_hour, view.end_hour)}
        />
      </div>

      {view.is_default && (
        <p className="mt-3 rounded-xl border border-border-subtle bg-surface-subtle px-3 py-2 font-body text-sm text-[#556274]">
          This is the default: 9 PM to 9 AM. You have not chosen your own hours yet.
        </p>
      )}

      {view.on && (
        <div className="mt-3 flex flex-wrap items-center gap-2 font-body text-sm text-ink">
          <label className="flex items-center gap-2">
            From
            <select
              className={selectCls}
              value={view.start_hour}
              disabled={!canManage || busy}
              onChange={(e) => save(true, Number(e.target.value), view.end_hour)}
              aria-label="Quiet time starts"
            >
              {HOURS.map((h) => <option key={h.value} value={h.value}>{h.label}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2">
            to
            <select
              className={selectCls}
              value={view.end_hour}
              disabled={!canManage || busy}
              onChange={(e) => save(true, view.start_hour, Number(e.target.value))}
              aria-label="Quiet time ends"
            >
              {HOURS.map((h) => <option key={h.value} value={h.value}>{h.label}</option>)}
            </select>
          </label>
          <span className="text-[#556274]">(India time)</span>
        </div>
      )}

      {view.on && view.still_comes_through.length > 0 && (
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

function AlertLine({ row, canManage, onChange }: { row: AlertRowView; canManage: boolean; onChange: (key: string, on: boolean, who?: WhoChoice[]) => Promise<void> }) {
  const [busy, setBusy] = useState(false);

  async function run(on: boolean, who?: WhoChoice[]) {
    setBusy(true);
    try {
      await onChange(row.key, on, who);
    } finally {
      setBusy(false);
    }
  }

  function toggleWho(w: WhoChoice) {
    const has = row.who.includes(w);
    const next = has ? row.who.filter((x) => x !== w) : [...row.who, w];
    if (next.length === 0) {
      toast.error("Pick at least one person to get this alert.");
      return;
    }
    void run(row.on, next);
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
        <SwitchPill on={row.on} disabled={!canManage || !!row.locked} loading={busy} aria-label={row.locked ? `${row.label} (always on)` : row.label} onChange={(next) => run(next)} />
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
                disabled={!canManage || busy || !!row.who_fixed}
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

  async function changeAlert(key: string, on: boolean, who?: WhoChoice[]) {
    try {
      await automationsApi.setAlert(key, on, who);
      await mutate();
    } catch (e) {
      toast.error(errText(e, "Could not save this alert."));
    }
  }

  if (authLoading) return null;
  if (!canView) {
    return <p className="font-body text-sm text-[#556274]">You do not have access to alert settings.</p>;
  }

  return (
    <div className="space-y-4">
      <header>
        <h1 className="font-label text-xl font-bold text-ink">Alerts</h1>
        <p className="mt-1 font-body text-sm text-[#556274]">Choose what Anril tells you about, and who hears it.</p>
      </header>

      {isLoading && <div className="card h-24 animate-pulse rounded-3xl bg-border-subtle" />}
      {error && !data && (
        <p role="alert" className="rounded-xl border border-border-subtle bg-surface-subtle px-3 py-2 font-body text-sm text-ink">
          Could not load your alerts. Please refresh.
        </p>
      )}

      {data && (
        <>
          <QuietTimeCard view={data.quiet_time} canManage={canManage} onSaved={() => void mutate()} />
          {groupAlertsByArea(data.alerts).map((g) => (
            <section key={g.area} aria-label={g.area} className="space-y-2">
              <h2 className="font-label text-xs font-bold uppercase tracking-wider text-[#556274]">{g.area}</h2>
              <ul className="space-y-2">
                {g.rows.map((r) => <AlertLine key={r.key} row={r as AlertRowView} canManage={canManage} onChange={changeAlert} />)}
              </ul>
            </section>
          ))}
        </>
      )}
    </div>
  );
}
