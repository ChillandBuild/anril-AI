"use client";
import { useCallback, useEffect, useState } from "react";
import { Lock, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  companionsApi,
  type ApiError,
  type CompanionDiary,
  type CompanionMemoryFact,
  type CompanionPerson,
} from "@/lib/api";
import { ConfirmModal } from "@/components/ConfirmModal";
import { SECTION_LABEL, layoutMemoryGraph } from "@/components/agents/memoryGraph";
import { BTN_SECONDARY, CARD, ErrorNote, LoadingRows, formatDate } from "@/components/agents/ui";

/**
 * One person's memory for one character. Example: Karthik (48213) on
 * Maya: 4 facts as a list or a graph, and the Diary tab (the
 * "earlier today" note plus one line per past day); delete one fact or
 * diary line, or "Delete this person" to wipe their chats and memory with
 * every character.
 */
export function PersonMemory({
  characterId,
  person,
  onForgotten,
}: {
  characterId: string;
  person: CompanionPerson;
  onForgotten: () => void;
}) {
  const [facts, setFacts] = useState<CompanionMemoryFact[] | null>(null);
  const [error, setError] = useState("");
  const [privateReason, setPrivateReason] = useState("");
  const [view, setView] = useState<"list" | "diary" | "graph">("list");
  const [confirmForget, setConfirmForget] = useState(false);
  const [busy, setBusy] = useState(false);
  const name = person.display_name || person.external_user_id;

  const load = useCallback(() => {
    setError("");
    setPrivateReason("");
    setFacts(null);
    companionsApi
      .personMemory(characterId, person.external_user_id)
      .then((r) => setFacts(r.facts))
      .catch((e: ApiError) => (e.status === 403 ? setPrivateReason(e.message) : setError(e.message || "Could not load the memory.")));
  }, [characterId, person.external_user_id]);
  useEffect(load, [load]);

  const deleteFact = async (fact: CompanionMemoryFact) => {
    try {
      await companionsApi.deleteFact(characterId, person.external_user_id, fact.id);
      setFacts((f) => (f ? f.filter((x) => x.id !== fact.id) : f));
    } catch (e) {
      setError((e as Error).message || "Could not delete the fact.");
    }
  };

  const forget = async () => {
    setBusy(true);
    try {
      await companionsApi.forgetPerson(person.external_user_id);
      setConfirmForget(false);
      onForgotten();
    } catch (e) {
      setError((e as Error).message || "Could not delete this person.");
      setConfirmForget(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={cn(CARD, "space-y-4")} aria-labelledby="person-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="person-title" className="text-base font-semibold text-ink">{name}</h2>
          <p className="text-xs text-ink-muted">
            User id {person.external_user_id} · {person.message_count} messages · last seen {formatDate(person.last_seen_at)}
          </p>
        </div>
        <button type="button" onClick={() => setConfirmForget(true)} className={cn(BTN_SECONDARY, "min-h-8 px-3 text-danger")}>
          <Trash2 size={14} aria-hidden="true" /> Delete this person
        </button>
      </div>

      {error && <ErrorNote message={error} onRetry={load} />}

      {privateReason ? (
        <div role="status" className="flex items-start gap-2 rounded-xl bg-surface-mid px-4 py-3 text-sm text-ink-secondary">
          <Lock size={15} className="mt-0.5 shrink-0" aria-hidden="true" /> {privateReason}
        </div>
      ) : facts === null && !error ? (
        <LoadingRows rows={3} />
      ) : facts ? (
        <>
          <div role="tablist" aria-label="View" className="flex gap-1">
            {(["list", "diary", "graph"] as const).map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={view === v}
                onClick={() => setView(v)}
                className={cn("rounded-lg px-3 py-1 text-xs font-medium capitalize", view === v ? "bg-primary/10 text-primary" : "text-ink-secondary hover:bg-surface-mid")}
              >
                {v}
              </button>
            ))}
          </div>
          {view === "diary" ? (
            <DiaryView characterId={characterId} externalUserId={person.external_user_id} name={name} />
          ) : facts.length === 0 ? (
            <p className="text-sm text-ink-secondary">No facts remembered about {name} yet.</p>
          ) : view === "list" ? (
            <FactList facts={facts} onDelete={deleteFact} />
          ) : (
            <FactGraph name={name} facts={facts} />
          )}
        </>
      ) : null}

      <ConfirmModal
        open={confirmForget}
        onClose={() => setConfirmForget(false)}
        onConfirm={forget}
        tone="danger"
        title={`Delete ${name}?`}
        description="This wipes their chats and everything remembered about them, with every one of your characters. It can't be undone. If they message again, they start fresh."
        confirmLabel="Delete this person"
        loading={busy}
        loadingLabel="Deleting…"
      />
    </section>
  );
}

function FactList({ facts, onDelete }: { facts: CompanionMemoryFact[]; onDelete: (f: CompanionMemoryFact) => void }) {
  return (
    <ul className="divide-y divide-border-subtle">
      {facts.map((f) => (
        <li key={f.id} className="flex items-start gap-3 py-2.5">
          <span className="mt-0.5 w-16 shrink-0 text-xs font-medium uppercase tracking-wide text-ink-muted">{SECTION_LABEL[f.section]}</span>
          <div className="min-w-0 flex-1">
            <p className={cn("text-sm text-ink", f.status === "closed" && "text-ink-muted line-through")}>{f.text}</p>
            <p className="text-xs text-ink-muted">
              Learned by {f.learned_by}
              {f.valid_from ? ` · since ${formatDate(f.valid_from)}` : ""}
              {f.status === "closed" ? ` · no longer true${f.valid_to ? ` from ${formatDate(f.valid_to)}` : ""}` : ""}
            </p>
          </div>
          <button type="button" onClick={() => onDelete(f)} aria-label={`Delete fact: ${f.text}`} className="rounded-lg p-1.5 text-ink-muted hover:bg-danger/5 hover:text-danger">
            <Trash2 size={14} aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  );
}

/** "2026-11-09" → "9 Nov 2026", read as a calendar day (never shifted by the viewer's timezone). */
function dayLabel(day: string | null): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(day ?? "");
  if (!m) return "—";
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

// The diary job clears the note within an hour of the person's midnight; until then it is yesterday's.
function recapLabel(day: string | null): string {
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  return !day || day === today ? "Earlier today" : `So far on ${dayLabel(day)}`;
}

type DiaryTarget = { kind: "today" } | { kind: "day"; day: string };

/** The character's own diary about this person: what it re-reads before each reply. */
function DiaryView({ characterId, externalUserId, name }: { characterId: string; externalUserId: string; name: string }) {
  const [diary, setDiary] = useState<CompanionDiary | null>(null);
  const [error, setError] = useState("");
  const [target, setTarget] = useState<DiaryTarget | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError("");
    setDiary(null);
    companionsApi
      .personDiary(characterId, externalUserId)
      .then(setDiary)
      .catch((e: ApiError) => setError(e.message || "Could not load the diary."));
  }, [characterId, externalUserId]);
  useEffect(load, [load]);

  const remove = async () => {
    if (!target) return;
    setBusy(true);
    try {
      if (target.kind === "today") {
        await companionsApi.deleteRecap(characterId, externalUserId);
        setDiary((d) => (d ? { ...d, today: null } : d));
      } else {
        await companionsApi.deleteDiaryDay(characterId, externalUserId, target.day);
        setDiary((d) => (d ? { ...d, days: d.days.filter((x) => x.day !== target.day) } : d));
      }
      setTarget(null);
    } catch (e) {
      setError((e as Error).message || "Could not delete it.");
      setTarget(null);
    } finally {
      setBusy(false);
    }
  };

  if (error) return <ErrorNote message={error} onRetry={load} />;
  if (!diary) return <LoadingRows rows={3} />;
  if (!diary.today && diary.days.length === 0) {
    return (
      <p className="text-sm text-ink-secondary">
        No diary about {name} yet. A line is written after each day with at least 3 messages from them.
      </p>
    );
  }
  return (
    <>
      <ul className="divide-y divide-border-subtle">
        {diary.today && (
          <DiaryRow
            label={recapLabel(diary.today.day)}
            text={diary.today.text}
            multiline
            onDelete={() => setTarget({ kind: "today" })}
            deleteLabel="Delete the note from earlier today"
          />
        )}
        {diary.days.map((d) => (
          <DiaryRow
            key={d.day}
            label={dayLabel(d.day)}
            text={d.text}
            onDelete={() => setTarget({ kind: "day", day: d.day })}
            deleteLabel={`Delete the diary line for ${dayLabel(d.day)}`}
          />
        ))}
      </ul>
      <ConfirmModal
        open={target !== null}
        onClose={() => setTarget(null)}
        onConfirm={remove}
        tone="danger"
        title={target?.kind === "today" ? "Delete the note from earlier today?" : `Delete the line for ${target?.kind === "day" ? dayLabel(target.day) : ""}?`}
        description={`The character won't see it again before replying to ${name}. The chat messages themselves stay. It can't be undone.`}
        confirmLabel="Delete"
        loading={busy}
        loadingLabel="Deleting…"
      />
    </>
  );
}

function DiaryRow({
  label,
  text,
  multiline = false,
  onDelete,
  deleteLabel,
}: {
  label: string;
  text: string;
  multiline?: boolean;
  onDelete: () => void;
  deleteLabel: string;
}) {
  return (
    <li className="flex items-start gap-3 py-2.5">
      <span className="mt-0.5 w-24 shrink-0 text-xs font-medium text-ink-muted">{label}</span>
      <p className={cn("min-w-0 flex-1 text-sm text-ink", multiline && "whitespace-pre-line")}>{text}</p>
      <button type="button" onClick={onDelete} aria-label={deleteLabel} className="rounded-lg p-1.5 text-ink-muted hover:bg-danger/5 hover:text-danger">
        <Trash2 size={14} aria-hidden="true" />
      </button>
    </li>
  );
}

function FactGraph({ name, facts }: { name: string; facts: CompanionMemoryFact[] }) {
  const { nodes, edges, size } = layoutMemoryGraph(name, facts);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const short = (text: string) => (text.length > 22 ? `${text.slice(0, 21)}…` : text);
  return (
    <svg viewBox={`-60 -10 ${size + 120} ${size + 20}`} role="img" aria-label={`Memory graph for ${name}: ${facts.length} facts`} className="mx-auto w-full max-w-xl">
      {edges.map((e) => {
        const a = byId.get(e.from)!;
        const b = byId.get(e.to)!;
        return <line key={`${e.from}-${e.to}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#cbd5e1" strokeWidth={1} />;
      })}
      {nodes.map((n) => (
        <g key={n.id}>
          <title>{n.label}</title>
          <circle
            cx={n.x}
            cy={n.y}
            r={n.kind === "person" ? 22 : n.kind === "section" ? 14 : 5}
            fill={n.kind === "person" ? "#038285" : n.kind === "section" ? "#e6f4f4" : n.closed ? "#cbd5e1" : "#2fb3b6"}
            stroke={n.kind === "section" ? "#038285" : "none"}
          />
          <text
            x={n.x}
            y={n.kind === "fact" ? n.y + 15 : n.y + (n.kind === "person" ? 36 : 28)}
            textAnchor="middle"
            className={n.kind === "fact" ? "fill-slate-500 text-[9px]" : "fill-slate-800 text-[11px] font-semibold"}
          >
            {n.kind === "fact" ? short(n.label) : n.label}
          </text>
        </g>
      ))}
    </svg>
  );
}
