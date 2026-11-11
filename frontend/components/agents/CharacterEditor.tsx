"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { companionKbApi, companionsApi, type ApiError, type Companion, type CompanionStatus, type KbCollection } from "@/lib/api";
import { LANGUAGES, MOODS, changedFields, collectionIdOf, linesToList, ownReasoningOn } from "@/components/agents/characterForm";
import { saveErrorMessage } from "@/components/agents/formErrors";
import { BTN_PRIMARY, CARD, Field, INPUT, StatusPill } from "@/components/agents/ui";

type Tab = "persona" | "memory" | "knowledge";
type Errors = Record<string, string>;

const TABS: { id: Tab; label: string }[] = [
  { id: "persona", label: "Persona" },
  { id: "memory", label: "Memory" },
  { id: "knowledge", label: "Knowledge" },
];

/**
 * Edit one character. Example: the owner opens Maya, sets
 * default mood to warm, picks the "Product guides" collection, sets Live, Save →
 * one PATCH with just those three fields. Switching "Answer from its own reasoning"
 * off sends just { own_reasoning: false }.
 */
export function CharacterEditor({ initial }: { initial: Companion }) {
  const [saved, setSaved] = useState(initial);
  const [draft, setDraft] = useState(initial);
  const [tab, setTab] = useState<Tab>("persona");
  const [errors, setErrors] = useState<Errors>({});
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [justSaved, setJustSaved] = useState(false);

  const changes = changedFields(saved, draft);
  const dirty = Object.keys(changes).length > 0;

  const set = <K extends keyof Companion>(key: K, value: Companion[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setErrors((e) => (e[key as string] ? { ...e, [key as string]: "" } : e));
    setJustSaved(false);
  };

  const save = async () => {
    setSaving(true);
    setMessage("");
    setErrors({});
    try {
      const updated = await companionsApi.update(saved.id, changes);
      setSaved(updated);
      setDraft(updated);
      setJustSaved(true);
    } catch (err) {
      const { fields, message: msg } = saveErrorMessage(err);
      setErrors(fields);
      setMessage(msg);
      // Jump to the tab that holds the first bad field.
      const first = Object.keys(fields)[0];
      if (first) setTab(tabOf(first));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className={cn(CARD, "flex flex-wrap items-center gap-3")}>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-base font-semibold text-ink">{saved.name}</h2>
            <StatusPill status={saved.status} />
          </div>
          <p className="text-xs text-ink-muted">Draft characters work only in the Playground. Live ones answer on your site.</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-ink-secondary">
          Status
          <select
            value={draft.status}
            onChange={(e) => set("status", e.target.value as CompanionStatus)}
            className={cn(INPUT, "w-auto py-1.5")}
          >
            <option value="draft">Draft</option>
            <option value="live">Live</option>
            <option value="paused">Paused</option>
          </select>
        </label>
        <button type="button" onClick={save} disabled={!dirty || saving} className={BTN_PRIMARY}>
          {saving ? "Saving…" : "Save"}
        </button>
        <span aria-live="polite" className="sr-only">
          {justSaved ? "Saved" : ""}
        </span>
        {justSaved && !dirty && <span className="text-xs text-success">Saved</span>}
      </div>

      {message && (
        <div role="alert" className="rounded-xl border border-danger/20 bg-danger/5 px-4 py-3 text-sm text-danger">
          {message}
        </div>
      )}

      <div role="tablist" aria-label="Character settings" className="flex gap-1 border-b border-border-subtle">
        {TABS.map((t) => {
          const hasError = Object.keys(errors).some((f) => errors[f] && tabOf(f) === t.id);
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={tab === t.id}
              aria-controls={`panel-${t.id}`}
              onClick={() => setTab(t.id)}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                tab === t.id ? "border-primary text-primary" : "border-transparent text-ink-secondary hover:text-ink",
              )}
            >
              {t.label}
              {hasError && <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-danger align-middle" aria-label="has errors" />}
            </button>
          );
        })}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className={CARD}>
        {tab === "persona" && <PersonaTab draft={draft} set={set} errors={errors} />}
        {tab === "memory" && <MemoryTab draft={draft} set={set} errors={errors} />}
        {tab === "knowledge" && <KnowledgeTab draft={draft} set={set} errors={errors} />}
      </div>
    </div>
  );
}

const MEMORY_FIELDS = new Set(["memory_level", "memory_engine", "history_messages", "privacy_mode"]);
function tabOf(field: string): Tab {
  if (MEMORY_FIELDS.has(field)) return "memory";
  if (field === "knowledge_collection_id" || field === "own_reasoning") return "knowledge";
  return "persona";
}

type TabProps = {
  draft: Companion;
  set: <K extends keyof Companion>(key: K, value: Companion[K]) => void;
  errors: Errors;
};

function invalid(errors: Errors, id: string) {
  return errors[id] ? { "aria-invalid": true, "aria-describedby": `${id}-error` } : {};
}

/** A list field edited as one item per line. Keeps the raw text so typing a newline isn't eaten. */
function ListField({ id, label, hint, value, onChange, errors }: {
  id: string; label: string; hint: string; value: string[]; onChange: (v: string[]) => void; errors: Errors;
}) {
  const [text, setText] = useState(value.join("\n"));
  useEffect(() => {
    if (linesToList(text).join("\n") !== value.join("\n")) setText(value.join("\n"));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resync only when the saved value changes
  }, [value]);
  return (
    <Field id={id} label={label} hint={hint} error={errors[id]}>
      <textarea
        id={id}
        rows={3}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          onChange(linesToList(e.target.value));
        }}
        className={INPUT}
        {...invalid(errors, id)}
      />
    </Field>
  );
}

function PersonaTab({ draft, set, errors }: TabProps) {
  const text = (id: "name" | "role" | "temperament", label: string, hint: string) => (
    <Field id={id} label={label} hint={hint} error={errors[id]}>
      <input id={id} value={draft[id]} onChange={(e) => set(id, e.target.value)} className={INPUT} {...invalid(errors, id)} />
    </Field>
  );
  const area = (id: "backstory" | "speaking_style", label: string, hint: string) => (
    <Field id={id} label={label} hint={hint} error={errors[id]}>
      <textarea id={id} rows={3} value={draft[id]} onChange={(e) => set(id, e.target.value)} className={INPUT} {...invalid(errors, id)} />
    </Field>
  );
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {text("name", "Name", "What customers see, e.g. Maya.")}
      <Field id="industry" label="Industry" error={errors.industry}>
        <select id="industry" value={draft.industry} onChange={(e) => set("industry", e.target.value as Companion["industry"])} className={INPUT}>
          <option value="general">General</option>
          <option value="astrology">Astrology</option>
        </select>
      </Field>
      <div className="md:col-span-2">{text("role", "Role", "One line, e.g. Friendly guide who answers product questions.")}</div>
      <div className="md:col-span-2">{area("backstory", "Backstory", "Who they are, in a few sentences.")}</div>
      <div className="md:col-span-2">{area("speaking_style", "Speaking style", "How they talk, e.g. warm, short sentences, Tanglish.")}</div>
      <div className="md:col-span-2">
        <ListField id="sample_lines" label="Sample lines" hint="Up to 10, one per line." value={draft.sample_lines} onChange={(v) => set("sample_lines", v)} errors={errors} />
      </div>
      <ListField id="goals" label="Goals" hint="Up to 5, one per line." value={draft.goals} onChange={(v) => set("goals", v)} errors={errors} />
      <ListField id="rules" label="Rules" hint="Up to 30, one per line." value={draft.rules} onChange={(v) => set("rules", v)} errors={errors} />
      {text("temperament", "Temperament", "e.g. Patient, never preachy.")}
      <Field id="default_mood" label="Default mood" error={errors.default_mood}>
        <select id="default_mood" value={draft.default_mood} onChange={(e) => set("default_mood", e.target.value as Companion["default_mood"])} className={cn(INPUT, "capitalize")}>
          {MOODS.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </Field>
      <Field id="language" label="Language" error={errors.language}>
        <select id="language" value={draft.language} onChange={(e) => set("language", e.target.value)} className={INPUT}>
          {LANGUAGES.some((l) => l.value === draft.language) ? null : <option value={draft.language}>{draft.language}</option>}
          {LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>{l.label}</option>
          ))}
        </select>
      </Field>
    </div>
  );
}

function MemoryTab({ draft, set, errors }: TabProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Field id="memory_level" label="Memory level" error={errors.memory_level} hint="Level 2 remembers facts about each person across chats.">
        <select id="memory_level" value={draft.memory_level} onChange={(e) => set("memory_level", Number(e.target.value) as 1 | 2)} className={INPUT}>
          <option value={1}>Level 1: recent messages only</option>
          <option value={2}>Level 2: remembers facts</option>
        </select>
      </Field>
      {draft.memory_level === 2 && (
        <Field id="memory_engine" label="Memory engine" error={errors.memory_engine}>
          <select id="memory_engine" value={draft.memory_engine} onChange={(e) => set("memory_engine", e.target.value as Companion["memory_engine"])} className={INPUT}>
            <option value="card">Card (built in)</option>
            <option value="mem0">mem0</option>
          </select>
        </Field>
      )}
      <Field id="history_messages" label="Recent messages read" hint="2 to 50. Every reply reads this many recent messages." error={errors.history_messages}>
        <input
          id="history_messages"
          type="number"
          min={2}
          max={50}
          value={draft.history_messages}
          onChange={(e) => set("history_messages", Number(e.target.value))}
          className={INPUT}
          {...invalid(errors, "history_messages")}
        />
      </Field>
      <Field id="privacy_mode" label="Who can read the memory" error={errors.privacy_mode}>
        <select id="privacy_mode" value={draft.privacy_mode} onChange={(e) => set("privacy_mode", e.target.value as "A" | "B")} className={INPUT}>
          <option value="A">You and the character (you can see the facts)</option>
          <option value="B">Only the character (private to each person)</option>
        </select>
      </Field>
    </div>
  );
}

function fileCount(n: number): string {
  return `${n} ${n === 1 ? "file" : "files"}`;
}

function KnowledgeTab({ draft, set, errors }: TabProps) {
  const [collections, setCollections] = useState<KbCollection[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const load = useCallback(() => {
    setLoadError("");
    companionKbApi
      .listCollections()
      .then(setCollections)
      .catch((e: ApiError) => setLoadError(e.message || "Could not load the collections."));
  }, []);
  useEffect(load, [load]);

  const current = collectionIdOf(draft);
  const loading = collections === null && !loadError;
  return (
    <div className="max-w-md space-y-5">
      <div className="space-y-1.5">
        <Field
          id="knowledge_collection_id"
          label="Collection"
          hint="The character reads only the files in this collection. Add files on the Upload page."
          error={errors.knowledge_collection_id}
        >
          <select
            id="knowledge_collection_id"
            value={current ?? ""}
            disabled={loading}
            onChange={(e) => set("knowledge_collection_id", e.target.value || null)}
            className={INPUT}
          >
            <option value="">No files</option>
            {current && !(collections ?? []).some((c) => c.id === current) && <option value={current}>Current collection</option>}
            {(collections ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({fileCount(c.book_count)})</option>
            ))}
          </select>
        </Field>
        {loading && <p className="text-xs text-ink-muted">Loading collections…</p>}
        {loadError && (
          <p role="alert" className="text-xs text-danger">
            Could not load the collections. {loadError}{" "}
            <button type="button" onClick={load} className="font-medium underline underline-offset-2">Retry</button>
          </p>
        )}
        {collections && collections.length === 0 && (
          <p className="text-xs text-ink-muted">
            No collections yet.{" "}
            <Link href="/dashboard/agents/collections" className="font-medium text-primary underline underline-offset-2">Create one</Link>
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <label htmlFor="own_reasoning" className="flex items-start gap-3 text-sm font-medium text-ink">
          <input
            id="own_reasoning"
            type="checkbox"
            role="switch"
            checked={ownReasoningOn(draft)}
            onChange={(e) => set("own_reasoning", e.target.checked)}
            aria-describedby="own_reasoning-hint"
            className="mt-0.5 h-4 w-4 shrink-0 rounded border-border-subtle accent-primary"
          />
          Answer from its own reasoning when no file covers the question
        </label>
        <p id="own_reasoning-hint" className="pl-7 text-xs text-ink-muted">
          Off = documents only. The character says politely that its material does not cover the question.
        </p>
        {errors.own_reasoning && <p role="alert" className="pl-7 text-xs text-danger">{errors.own_reasoning}</p>}
      </div>
    </div>
  );
}
