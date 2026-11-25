"use client";

import { useState } from "react";
import { Check, Pencil, Plus, Trash2, Users, X } from "lucide-react";
import { toast } from "sonner";
import { api, CallTeam, CallTeamsResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

type Person = { caller_id: string; name: string | null; user_id: string | null };

interface TeamsPanelProps {
  data: CallTeamsResponse;
  /** Reload the teams (and the people list that shows each person's team). */
  onChanged: () => void | Promise<unknown>;
}

function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

/** Call IQ › Team › Teams. Shown to managers only: make teams, rename, delete, tick who is in a team, pick leaders. */
export default function TeamsPanel({ data, onChanged }: TeamsPanelProps) {
  const [newName, setNewName] = useState("");
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  // Everyone who can be put in a team: members of any team + people in no team.
  const everyone: Person[] = [...data.data.flatMap((t) => t.members), ...data.unteamed];

  async function run(fn: () => Promise<unknown>, okMsg?: string) {
    setBusy(true);
    try {
      await fn();
      await onChanged();
      if (okMsg) toast.success(okMsg);
      return true;
    } catch (e) {
      toast.error(errText(e, "Could not save. Try again."));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function addTeam() {
    const name = newName.trim();
    if (!name) return;
    const ok = await run(() => api.callTeams.create(name), `${name} created`);
    if (ok) {
      setNewName("");
      setAdding(false);
    }
  }

  return (
    <section className="mb-6 min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5" aria-label="Teams">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
            <Users size={16} className="shrink-0" /> Teams
          </h2>
          <p className="mt-0.5 font-body text-xs text-ink-muted">
            Put telecallers in teams. A team leader sees only their own team&apos;s people, leads and calls.
          </p>
        </div>
        {!adding && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            disabled={!data.teams_ready}
            className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-3 py-2 font-body text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            <Plus size={14} /> Team
          </button>
        )}
      </div>

      {!data.teams_ready && (
        <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 font-body text-xs font-semibold text-amber-800">
          Teams are not switched on yet. Ask support to turn them on.
        </p>
      )}

      {adding && (
        <form
          className="mt-3 flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void addTeam();
          }}
        >
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            maxLength={60}
            placeholder="Team name, e.g. Team A"
            aria-label="New team name"
            className="min-w-0 flex-1 rounded-xl border border-border bg-white px-3 py-2 font-body text-sm text-ink outline-none focus:border-primary"
          />
          <button
            type="submit"
            disabled={busy || !newName.trim()}
            className="rounded-xl bg-primary px-3 py-2 font-body text-xs font-semibold text-white disabled:opacity-50"
          >
            Create
          </button>
          <button
            type="button"
            onClick={() => {
              setAdding(false);
              setNewName("");
            }}
            className="rounded-xl px-3 py-2 font-body text-xs font-semibold text-ink-muted hover:bg-surface-soft"
          >
            Cancel
          </button>
        </form>
      )}

      {note && (
        <p className="mt-3 flex items-start justify-between gap-2 rounded-xl bg-amber-50 px-3 py-2 font-body text-xs font-semibold text-amber-800">
          <span>{note}</span>
          <button type="button" aria-label="Dismiss note" onClick={() => setNote(null)} className="shrink-0">
            <X size={14} />
          </button>
        </p>
      )}

      {data.teams_ready && data.data.length === 0 && !adding && (
        <p className="mt-4 font-body text-sm text-ink-muted">No teams yet. Tap ＋ Team to make the first one.</p>
      )}

      <div className="mt-4 grid min-w-0 gap-3 lg:grid-cols-2">
        {data.data.map((team) => (
          <TeamCard key={team.id} team={team} everyone={everyone} allTeams={data.data} busy={busy} run={run} setNote={setNote} />
        ))}
      </div>
    </section>
  );
}

interface TeamCardProps {
  team: CallTeam;
  everyone: Person[];
  allTeams: CallTeam[];
  busy: boolean;
  run: (fn: () => Promise<unknown>, okMsg?: string) => Promise<boolean>;
  setNote: (n: string | null) => void;
}

function TeamCard({ team, everyone, allTeams, busy, run, setNote }: TeamCardProps) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(team.name);
  const [pickMembers, setPickMembers] = useState(false);
  const [pickLeaders, setPickLeaders] = useState(false);

  const memberIds = new Set(team.members.map((m) => m.caller_id));
  const leaderIds = new Set(team.leaders.map((l) => l.user_id));
  const teamOf = (callerId: string) => allTeams.find((t) => t.members.some((m) => m.caller_id === callerId));
  const leaderChoices = everyone.filter((p) => p.user_id);

  async function toggleMember(callerId: string) {
    const next = new Set(memberIds);
    if (next.has(callerId)) next.delete(callerId);
    else next.add(callerId);
    await run(() => api.callTeams.setMembers(team.id, Array.from(next)));
  }

  async function toggleLeader(userId: string) {
    const next = new Set(leaderIds);
    if (next.has(userId)) next.delete(userId);
    else next.add(userId);
    await run(async () => {
      const res = await api.callTeams.setLeaders(team.id, Array.from(next));
      setNote(res.note ?? null);
    });
  }

  async function saveName() {
    const trimmed = name.trim();
    if (!trimmed || trimmed === team.name) {
      setRenaming(false);
      setName(team.name);
      return;
    }
    const ok = await run(() => api.callTeams.rename(team.id, trimmed), "Team renamed");
    if (ok) setRenaming(false);
  }

  async function removeTeam() {
    if (!window.confirm(`Delete ${team.name}? Its telecallers stay, they just have no team.`)) return;
    await run(() => api.callTeams.remove(team.id), `${team.name} deleted`);
  }

  return (
    <div className="min-w-0 rounded-xl border border-border bg-white p-3">
      <div className="flex min-w-0 items-center justify-between gap-2">
        {renaming ? (
          <form
            className="flex min-w-0 flex-1 items-center gap-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              void saveName();
            }}
          >
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={60}
              aria-label={`Rename ${team.name}`}
              className="min-w-0 flex-1 rounded-lg border border-border px-2 py-1 font-body text-sm text-ink outline-none focus:border-primary"
            />
            <button type="submit" aria-label="Save name" disabled={busy} className="rounded-lg p-1.5 text-primary hover:bg-surface-soft">
              <Check size={16} />
            </button>
            <button
              type="button"
              aria-label="Cancel rename"
              onClick={() => {
                setRenaming(false);
                setName(team.name);
              }}
              className="rounded-lg p-1.5 text-ink-muted hover:bg-surface-soft"
            >
              <X size={16} />
            </button>
          </form>
        ) : (
          <>
            <h3 className="min-w-0 truncate font-display text-sm font-bold text-ink">{team.name}</h3>
            <div className="flex shrink-0 items-center gap-1 max-md:gap-2">
              <button
                type="button"
                aria-label={`Rename ${team.name}`}
                onClick={() => setRenaming(true)}
                className="rounded-lg p-1.5 text-ink-muted hover:bg-surface-soft max-md:inline-flex max-md:h-9 max-md:w-9 max-md:items-center max-md:justify-center"
              >
                <Pencil size={14} />
              </button>
              <button
                type="button"
                aria-label={`Delete ${team.name}`}
                onClick={() => void removeTeam()}
                disabled={busy}
                className="rounded-lg p-1.5 text-red-600 hover:bg-red-50 disabled:opacity-50 max-md:inline-flex max-md:h-9 max-md:w-9 max-md:items-center max-md:justify-center"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </>
        )}
      </div>

      <div className="mt-3">
        <div className="flex items-center justify-between gap-2">
          <p className="font-body text-xs font-semibold text-ink-muted">Leaders</p>
          <button
            type="button"
            onClick={() => setPickLeaders((v) => !v)}
            className="inline-flex min-h-8 items-center px-2 font-body text-xs font-semibold text-primary hover:underline"
          >
            {pickLeaders ? "Done" : "Pick leaders"}
          </button>
        </div>
        {team.leaders.length === 0 ? (
          <p className="mt-1 font-body text-xs text-ink-muted">No leader yet.</p>
        ) : (
          <div className="mt-1 flex flex-wrap gap-1.5">
            {team.leaders.map((l) => (
              <span key={l.user_id} className="rounded-full bg-primary/10 px-2.5 py-1 font-body text-xs font-semibold text-primary">
                {l.name}
              </span>
            ))}
          </div>
        )}
        {pickLeaders && <TickList people={leaderChoices} isOn={(p) => !!p.user_id && leaderIds.has(p.user_id)} onToggle={(p) => (p.user_id ? toggleLeader(p.user_id) : undefined)} busy={busy} hint={() => null} />}
      </div>

      <div className="mt-3">
        <div className="flex items-center justify-between gap-2">
          <p className="font-body text-xs font-semibold text-ink-muted">Telecallers ({team.members.length})</p>
          <button
            type="button"
            onClick={() => setPickMembers((v) => !v)}
            className="inline-flex min-h-8 items-center px-2 font-body text-xs font-semibold text-primary hover:underline"
          >
            {pickMembers ? "Done" : "Pick telecallers"}
          </button>
        </div>
        {team.members.length === 0 ? (
          <p className="mt-1 font-body text-xs text-ink-muted">Nobody in this team yet.</p>
        ) : (
          <div className="mt-1 flex flex-wrap gap-1.5">
            {team.members.map((m) => (
              <span key={m.caller_id} className="rounded-full bg-surface-soft px-2.5 py-1 font-body text-xs text-ink">
                {m.name ?? "Telecaller"}
              </span>
            ))}
          </div>
        )}
        {pickMembers && (
          <TickList
            people={everyone}
            isOn={(p) => memberIds.has(p.caller_id)}
            onToggle={(p) => toggleMember(p.caller_id)}
            busy={busy}
            hint={(p) => {
              const other = teamOf(p.caller_id);
              return other && other.id !== team.id ? `in ${other.name}, will move` : null;
            }}
          />
        )}
      </div>
    </div>
  );
}

interface TickListProps {
  people: Person[];
  isOn: (p: Person) => boolean;
  onToggle: (p: Person) => void | Promise<unknown>;
  busy: boolean;
  hint: (p: Person) => string | null;
}

function TickList({ people, isOn, onToggle, busy, hint }: TickListProps) {
  if (people.length === 0) {
    return <p className="mt-2 font-body text-xs text-ink-muted">No telecallers to pick yet. Add them in Settings › Team &amp; roles.</p>;
  }
  return (
    <ul className="mt-2 max-h-56 min-w-0 divide-y divide-border overflow-y-auto rounded-xl border border-border">
      {people.map((p) => {
        const on = isOn(p);
        const h = hint(p);
        return (
          <li key={p.caller_id}>
            <label className={cn("flex cursor-pointer items-center gap-2.5 px-3 py-2 hover:bg-surface-soft", busy && "opacity-60")}>
              <input type="checkbox" checked={on} disabled={busy} onChange={() => void onToggle(p)} className="h-4 w-4 shrink-0 accent-primary" />
              <span className="min-w-0 flex-1 truncate font-body text-sm text-ink">{p.name ?? "Telecaller"}</span>
              {h && !on && <span className="shrink-0 font-body text-xs text-ink-muted">{h}</span>}
            </label>
          </li>
        );
      })}
    </ul>
  );
}
