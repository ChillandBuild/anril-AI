"use client";
import { useCallback, useEffect, useState } from "react";
import { Lock, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { companionsApi, type ApiError, type CompanionMemoryFact, type CompanionPerson } from "@/lib/api";
import { ConfirmModal } from "@/components/ConfirmModal";
import { SECTION_LABEL, layoutMemoryGraph } from "@/components/agents/memoryGraph";
import { BTN_SECONDARY, CARD, ErrorNote, LoadingRows, formatDate } from "@/components/agents/ui";

/**
 * One person's memory for one character. Example: Karthik (48213) on
 * Jothidar AI: 4 facts as a list or a graph; delete one fact, or "Delete
 * this person" to wipe their chats and facts with every character.
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
  const [view, setView] = useState<"list" | "graph">("list");
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
      ) : facts && facts.length === 0 ? (
        <p className="text-sm text-ink-secondary">Nothing remembered about {name} yet.</p>
      ) : facts ? (
        <>
          <div role="tablist" aria-label="View" className="flex gap-1">
            {(["list", "graph"] as const).map((v) => (
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
          {view === "list" ? <FactList facts={facts} onDelete={deleteFact} /> : <FactGraph name={name} facts={facts} />}
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
