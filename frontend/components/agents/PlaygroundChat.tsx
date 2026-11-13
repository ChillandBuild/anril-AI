"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeftRight, Loader2, Wrench, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Select } from "@/components/ui/Select";
import {
  companionsApi,
  type ApiError,
  type Companion,
  type CompanionAppTool,
  type CompanionMemoryStatus,
  type CompanionModel,
  type CompanionReply,
  type CompanionToolCall,
  type PlaygroundDefaults,
  type PlaygroundSources,
  type TestPerson,
} from "@/lib/api";
import {
  chatErrorText,
  formatMs,
  formatToolCall,
  memoryStatusLine,
  modelChoices,
  modelLabel,
  pairCompareReplies,
  parseToolOutput,
  replySourceLine,
  saveMemoryResult,
  sourcesSetting,
  suggestionsFor,
  toolNameError,
} from "@/components/agents/playground";
import { CharacterSelect } from "@/components/agents/CharacterSelect";
import { Hero, PromptBox, chipClass } from "@/components/agents/PlaygroundParts";
import { TestPersonPicker, useTestPeople } from "@/components/agents/TestPersonPicker";
import { BTN_PRIMARY, BTN_SECONDARY, INPUT } from "@/components/agents/ui";

type ReplyBubble = {
  kind: "reply";
  text: string;
  mood: string | null;
  ms: number;
  model: string | null;
  label?: string;
  basis?: CompanionReply["basis"];
  sources?: CompanionReply["sources"];
  trace: string[];
};
type Bubble = { kind: "user"; text: string } | ReplyBubble | { kind: "error"; text: string };

/** A paused turn. `trace` = the lines from before the pause; /continue returns none, so they are kept here. */
type PendingTools = { turnId: string; calls: CompanionToolCall[]; started: number; trace: string[] };

/** "Use for <name>": idle, asking "are you sure", or saving. */
type UseFor = "idle" | "confirm" | "saving";
type SaveNote = { tone: "ok" | "info" | "error"; text: string; seeThem: boolean };

const BAR = "mx-auto mt-2 flex max-w-[720px] flex-wrap items-center justify-between gap-2 rounded-[10px] px-2.5 py-2 text-[12.5px]";
const SMALL_BTN = "min-h-8 px-3 text-[12.5px]";

/**
 * Chat with one character as the owner or as a test customer. Example: the owner types
 * "Which plan am I on?" and Maya answers, with grey lines under the reply saying what she
 * searched ("Memory card: 6 lines"). The model chip starts on Maya's saved model; trying
 * another is for this test chat only until "Use for Maya" is confirmed.
 */
export function PlaygroundChat({
  character,
  characters,
  onSelectCharacter,
  onCharacterSaved,
  sources,
  live,
  models,
}: {
  character: Companion;
  characters: Companion[];
  onSelectCharacter: (id: string) => void;
  /** The server's copy of the character after "Use for <name>" saved its model. */
  onCharacterSaved: (c: Companion) => void;
  /** The "Answer from" choice in Advanced; the only setting that differs from live chat. */
  sources: PlaygroundSources;
  live: PlaygroundDefaults;
  models: CompanionModel[];
}) {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<PendingTools | null>(null);
  const [tools, setTools] = useState<CompanionAppTool[]>([]);
  const [pick, setPick] = useState<string | null>(null);   // null = the character's own model
  const [useFor, setUseFor] = useState<UseFor>("idle");
  const [useForError, setUseForError] = useState("");
  const [savedModel, setSavedModel] = useState("");
  const [compare, setCompare] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  // Who the owner is testing as. null = You.
  const { people, setPeople, max, error: peopleError, reload: reloadPeople } = useTestPeople();
  const [personId, setPersonId] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);   // bumped by Start over so the screen clears even though the id is the same
  const you = people?.find((p) => p.is_you);
  const person: TestPerson | undefined = people?.find((p) => p.external_user_id === personId) ?? you;

  const [memory, setMemory] = useState<CompanionMemoryStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveNote, setSaveNote] = useState<SaveNote | null>(null);

  // A reply that arrives for another character, person or cleared screen is dropped.
  const screenKey = `${character.id}|${person?.external_user_id ?? ""}|${epoch}`;
  const activeKey = useRef(screenKey);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [bubbles, pending]);

  // A different character or person starts a fresh screen (what they remember stays on the server).
  useEffect(() => {
    activeKey.current = screenKey;
    setBubbles([]);
    setPending(null);
    setBusy(false);
    setSaveNote(null);
  }, [screenKey]);

  // A different character starts on its own model again.
  useEffect(() => {
    setPick(null);
    setUseFor("idle");
    setUseForError("");
    setSavedModel("");
  }, [character.id]);

  const loadMemory = useCallback(() => {
    const id = person?.external_user_id;
    if (!id) return;
    const forKey = activeKey.current;
    companionsApi
      .testPersonMemory(character.id, id)
      .then((m) => {
        if (activeKey.current === forKey) setMemory(m);
      })
      .catch(() => {
        if (activeKey.current === forKey) setMemory(null);   // no line rather than a wrong one
      });
  }, [character.id, person?.external_user_id]);
  useEffect(() => {
    setMemory(null);
    loadMemory();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload only when the screen changes
  }, [screenKey]);

  const toBubble = (reply: CompanionReply, started: number, label?: string, priorTrace: string[] = []): ReplyBubble => ({
    kind: "reply",
    text: reply.text ?? "",
    mood: reply.mood,
    ms: performance.now() - started,
    model: reply.model ?? null,
    label,
    basis: reply.basis ?? null,
    sources: reply.sources ?? [],
    trace: [...priorTrace, ...(reply.trace ?? [])],
  });

  /** `priorTrace` = trace lines from the paused turn this reply continues. */
  const handle = (reply: CompanionReply, started: number, label?: string, priorTrace: string[] = []) => {
    if (label) {
      setBubbles((b) => [...b, toBubble(reply, started, label)]);
      return;
    }
    if (reply.memory) setMemory(reply.memory);
    if (reply.status === "tool_call" && reply.turn_id) {
      setPending({ turnId: reply.turn_id, calls: reply.tool_calls, started, trace: [...priorTrace, ...(reply.trace ?? [])] });
      return;
    }
    setPending(null);
    setBubbles((b) => [...b, toBubble(reply, started, undefined, priorTrace)]);
  };

  const trying = pick !== null && pick !== character.model;

  const send = async (given?: string) => {
    const message = (given ?? text).trim();
    if (!message || busy || pending) return;
    const forKey = screenKey;
    setText("");
    setBusy(true);
    setSaveNote(null);
    setBubbles((b) => [...b, { kind: "user", text: message }]);
    const started = performance.now();
    const base = {
      model: trying ? pick : undefined,   // the character's own model is what the server uses anyway
      settings: sourcesSetting(sources, live),
      test_person: person && !person.is_you ? person.external_user_id : undefined,
    };
    // Compare: the same message again, without memory, in parallel. Shown beside the first, labelled.
    const [main, bare] = await Promise.allSettled([
      companionsApi.testChat(character.id, message, { ...base, tools }),
      compare ? companionsApi.testChat(character.id, message, { ...base, use_memory: false }) : Promise.resolve(null),
    ]);
    if (activeKey.current !== forKey) return;   // the owner switched character or person meanwhile
    if (main.status === "fulfilled") handle(main.value, started);
    else setBubbles((b) => [...b, { kind: "error", text: chatErrorText(main.reason) }]);
    if (bare.status === "fulfilled" && bare.value) handle(bare.value, started, "Without memory");
    else if (bare.status === "rejected") setBubbles((b) => [...b, { kind: "error", text: `Without memory: ${chatErrorText(bare.reason)}` }]);
    setBusy(false);
  };

  const answerTools = async (results: { id: string; output: unknown }[]) => {
    if (!pending) return;
    const forKey = screenKey;
    setBusy(true);
    try {
      const reply = await companionsApi.continueTestChat(pending.turnId, results);
      if (activeKey.current === forKey) handle(reply, pending.started, undefined, pending.trace);
    } catch (err) {
      if (activeKey.current !== forKey) return;
      setPending(null);
      setBubbles((b) => [...b, { kind: "error", text: chatErrorText(err) }]);
    } finally {
      if (activeKey.current === forKey) setBusy(false);
    }
  };

  /** "Yes, switch": save the tried model on the character. Failure keeps the chip on the tried model. */
  const switchModel = async () => {
    if (!pick || useFor === "saving") return;
    const forId = character.id;
    setUseFor("saving");
    setUseForError("");
    try {
      const updated = await companionsApi.update(forId, { model: pick });
      if (activeKey.current.split("|")[0] !== forId) return;
      onCharacterSaved(updated);
      setPick(null);
      setUseFor("idle");
      setSavedModel(modelLabel(models, updated.model));
    } catch (err) {
      if (activeKey.current.split("|")[0] !== forId) return;
      setUseFor("confirm");
      setUseForError((err as ApiError).message || "Could not save. Try again.");
    }
  };

  const saveNow = async () => {
    const id = person?.external_user_id;
    if (!id || saving) return;
    const forKey = screenKey;
    setSaving(true);
    setSaveNote(null);
    try {
      const r = await companionsApi.saveTestPersonMemory(character.id, id);
      if (activeKey.current !== forKey) return;
      const res = saveMemoryResult(r.outcome, { facts: r.facts, character: character.name, person: person?.name ?? "", isYou: !!person?.is_you });
      setSaveNote(res);
      loadMemory();
    } catch (err) {
      if (activeKey.current !== forKey) return;
      setSaveNote({ tone: "error", text: (err as ApiError).message || "Could not save the memory. Try again.", seeThem: false });
    } finally {
      setSaving(false);
    }
  };

  const started = bubbles.length > 0 || !!pending;
  const choices = modelChoices(models, character.model, character.name);
  const tried = pick ? modelLabel(models, pick) : "";
  const own = modelLabel(models, character.model);
  const status = memory ? memoryStatusLine(memory, character) : null;
  const suggestions = suggestionsFor(character);

  return (
    <div>
      {started ? (
        <div ref={listRef} className="mx-auto mb-4 mt-4 max-h-[60vh] max-w-[720px] space-y-3 overflow-y-auto pr-1" aria-live="polite">
          {pairCompareReplies(bubbles).map((b, i) =>
            Array.isArray(b) ? (
              <div key={i} className="grid gap-3 sm:grid-cols-2">
                {/* pairCompareReplies only pairs two replies */}
                <ReplyView bubble={b[0] as ReplyBubble} heading="With memory" full />
                <ReplyView bubble={b[1] as ReplyBubble} heading="Without memory" full />
              </div>
            ) : b.kind === "user" ? (
              <div key={i} className="ml-auto w-fit max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-sm text-white">
                {b.text}
              </div>
            ) : b.kind === "reply" ? (
              <ReplyView key={i} bubble={b} heading={b.label} />
            ) : (
              <div key={i} role="alert" className="max-w-[85%] rounded-xl border border-danger/20 bg-danger/5 px-3.5 py-2 text-sm text-danger">
                {b.text}
              </div>
            ),
          )}
          {pending && <ToolAnswer calls={pending.calls} busy={busy} onAnswer={answerTools} />}
          {busy && !pending && <div className="text-xs text-ink-muted">{character.name} is typing…</div>}
        </div>
      ) : (
        <Hero title={`See what ${character.name} can do`} />
      )}

      <PromptBox
        id="playground-message"
        label="Message"
        value={text}
        onChange={setText}
        onSubmit={() => void send()}
        maxLength={4000}
        placeholder={pending ? "Answer the tool first" : `Message ${character.name}…`}
        disabled={!!pending}
        sendDisabled={busy || !!pending || !text.trim()}
        chips={
          <>
            {models.length > 0 && (
              <Select
                size="sm"
                aria-label="Model"
                className={cn("h-7 w-auto max-w-[260px] rounded-lg", trying && "border-amber-300 bg-amber-50 text-amber-900")}
                value={pick ?? character.model}
                onChange={(v) => {
                  setPick(v === character.model ? null : v);
                  setUseFor("idle");
                  setUseForError("");
                  setSavedModel("");
                }}
                options={choices}
              />
            )}
            <button
              type="button"
              aria-pressed={compare}
              onClick={() => setCompare((c) => !c)}
              title="Also answer without remembered facts or chat history, side by side"
              className={chipClass(compare)}
            >
              <ArrowLeftRight size={13} aria-hidden="true" /> Compare without memory
            </button>
          </>
        }
        pickers={
          <>
            <CharacterSelect characters={characters} value={character.id} onChange={onSelectCharacter} inline />
            <TestPersonPicker
              people={people}
              max={max}
              selectedId={person?.external_user_id ?? ""}
              onPick={setPersonId}
              onCreated={(p) => {
                setPeople((list) => [...(list ?? []), p]);
                setPersonId(p.external_user_id);
              }}
              onStartedOver={(p) => {
                setPeople((list) => (list ? list.map((x) => (x.external_user_id === p.external_user_id ? p : x)) : list));
                setEpoch((n) => n + 1);
              }}
              onDeleted={(p) => {
                setPeople((list) => (list ? list.filter((x) => x.external_user_id !== p.external_user_id) : list));
                if (person?.external_user_id === p.external_user_id) setPersonId(null);
              }}
              onOpen={reloadPeople}
            />
          </>
        }
      />
      {peopleError && <p role="alert" className="mx-auto mt-2 max-w-[720px] text-xs text-danger">{peopleError}</p>}

      {status && (
        <p className="mx-auto mt-2 flex max-w-[720px] flex-wrap items-center gap-x-1.5 text-xs text-ink-muted">
          <span>{status.text}</span>
          {status.canSave && (
            <>
              <span aria-hidden="true">·</span>
              <button type="button" onClick={() => void saveNow()} disabled={saving} className="inline-flex items-center gap-1 font-medium text-primary hover:underline disabled:opacity-60">
                {saving && <Loader2 size={12} className="animate-spin" aria-hidden="true" />} Save now
              </button>
            </>
          )}
        </p>
      )}
      {saveNote && (
        <p
          role={saveNote.tone === "error" ? "alert" : "status"}
          className={cn("mx-auto mt-1.5 max-w-[720px] text-xs", saveNote.tone === "ok" ? "text-success" : saveNote.tone === "error" ? "text-danger" : "text-ink-secondary")}
        >
          {saveNote.text}{" "}
          {saveNote.seeThem && (
            <Link href="/dashboard/agents/memories" className="font-medium text-primary hover:underline">
              See them →
            </Link>
          )}
        </p>
      )}

      {trying && useFor === "idle" && (
        <div className={cn(BAR, "bg-amber-50 text-amber-900")}>
          <span>
            Trying <b>{tried}</b> in this test chat only. Visitors still get <b>{own}</b>.
          </span>
          <button type="button" onClick={() => setUseFor("confirm")} className={cn(BTN_PRIMARY, SMALL_BTN)}>
            Use for {character.name}
          </button>
        </div>
      )}
      {trying && useFor !== "idle" && (
        <div className={cn(BAR, "bg-amber-50 text-amber-900")}>
          <span>
            From now on every visitor gets <b>{tried}</b> from {character.name}.
          </span>
          <span className="flex gap-2">
            <button type="button" disabled={useFor === "saving"} onClick={() => { setUseFor("idle"); setUseForError(""); }} className={cn(BTN_SECONDARY, SMALL_BTN)}>
              Cancel
            </button>
            <button type="button" disabled={useFor === "saving"} onClick={() => void switchModel()} className={cn(BTN_PRIMARY, SMALL_BTN)}>
              {useFor === "saving" ? "Saving…" : "Yes, switch"}
            </button>
          </span>
          {useForError && <span role="alert" className="w-full text-danger">{useForError}</span>}
        </div>
      )}
      {savedModel && !trying && (
        <p role="status" className="mx-auto mt-2 max-w-[720px] rounded-[10px] bg-green-100 px-2.5 py-2 text-[12.5px] text-success">
          Saved. {character.name} now answers with {savedModel}.
        </p>
      )}
      {compare && (
        <p className="mx-auto mt-2 max-w-[720px] text-xs text-ink-muted">
          Each reply comes twice: normal, and as if {character.name} had never met {person?.is_you === false ? person.name : "you"}.
        </p>
      )}

      {!started && (
        <div className="mx-auto mt-3.5 flex max-w-[720px] flex-wrap gap-1.5">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              disabled={busy}
              onClick={() => void send(s)}
              className="rounded-full border border-border bg-white px-3 py-1.5 text-[12.5px] text-ink transition-colors hover:bg-surface-mid disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <AppTools tools={tools} onChange={setTools} />
    </div>
  );
}

/** One answer: the text, where it came from, grey trace lines, and mood / model / time. */
function ReplyView({ bubble: b, heading, full }: { bubble: ReplyBubble; heading?: string; full?: boolean }) {
  const source = replySourceLine(b.basis, b.sources);
  const meta = [b.mood, b.model, formatMs(b.ms)].filter(Boolean).join(" · ");
  return (
    <div className={cn("min-w-0 space-y-1.5", full ? "w-full" : "max-w-[85%]")}>
      {heading && <div className="text-xs font-medium text-ink-secondary">{heading}</div>}
      <div className="whitespace-pre-wrap rounded-2xl rounded-bl-md bg-surface-mid px-3.5 py-2 text-sm text-ink">{b.text}</div>
      {source && <div className="px-1 text-xs text-ink-secondary">{source}</div>}
      {b.trace.length > 0 && (
        <ul aria-label="What was searched" className="space-y-0.5 border-l-2 border-primary/20 pl-2 text-xs text-ink-secondary">
          {b.trace.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      )}
      <div className="px-1 text-[11px] text-ink-muted">{meta}</div>
    </div>
  );
}

function ToolAnswer({ calls, busy, onAnswer }: { calls: CompanionToolCall[]; busy: boolean; onAnswer: (r: { id: string; output: unknown }[]) => void }) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  return (
    <div className="space-y-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm">
      {calls.map((c) => (
        <div key={c.id} className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-amber-900">
            <Wrench size={14} aria-hidden="true" />
            <span>asked your app:</span>
            <code className="break-all font-mono text-xs">{formatToolCall(c)}</code>
          </div>
          <label className="sr-only" htmlFor={`tool-${c.id}`}>Answer for {c.name}</label>
          <textarea
            id={`tool-${c.id}`}
            rows={2}
            value={answers[c.id] ?? ""}
            onChange={(e) => setAnswers((a) => ({ ...a, [c.id]: e.target.value }))}
            placeholder='Type what your app would answer, e.g. {"plan": "Pro"}'
            className={cn(INPUT, "font-mono text-xs")}
          />
        </div>
      ))}
      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy}
          className={cn(BTN_PRIMARY, "min-h-8")}
          onClick={() => onAnswer(calls.map((c) => ({ id: c.id, output: parseToolOutput(answers[c.id] ?? "") })))}
        >
          Send answer
        </button>
        <button
          type="button"
          disabled={busy}
          className={cn(BTN_SECONDARY, "min-h-8")}
          onClick={() => onAnswer(calls.map((c) => ({ id: c.id, output: { error: "The app skipped this tool." } })))}
        >
          Skip
        </button>
      </div>
    </div>
  );
}

/** Tools the business's app would offer, so the owner can test tool calls without their app. Folded away until needed. */
function AppTools({ tools, onChange }: { tools: CompanionAppTool[]; onChange: (t: CompanionAppTool[]) => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const add = () => {
    const err = toolNameError(name.trim(), tools.map((t) => t.name));
    if (err) return setError(err);
    onChange([...tools, { name: name.trim(), description: description.trim().slice(0, 500) }]);
    setName("");
    setDescription("");
    setError("");
  };
  return (
    <details className="mx-auto mt-4 max-w-[720px] rounded-xl border border-border-subtle px-3.5 py-2.5 text-sm">
      <summary className="cursor-pointer select-none text-ink-secondary">
        Your app&apos;s tools{tools.length > 0 ? ` (${tools.length})` : ""}
      </summary>
      <p className="mb-3 mt-2 text-xs text-ink-muted">Optional. Pretend your app offers these; you answer them by hand.</p>
      {tools.length > 0 && (
        <ul className="mb-3 space-y-1">
          {tools.map((t) => (
            <li key={t.name} className="flex items-center justify-between gap-2 rounded-lg bg-surface-mid px-2 py-1 font-mono text-xs">
              <span className="truncate">{t.name}</span>
              <button type="button" aria-label={`Remove ${t.name}`} onClick={() => onChange(tools.filter((x) => x.name !== t.name))} className="text-ink-muted hover:text-danger">
                <X size={13} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="space-y-2">
        <input aria-label="Tool name" value={name} onChange={(e) => setName(e.target.value)} placeholder="get_chart" className={cn(INPUT, "font-mono text-xs")} />
        <input aria-label="What it does" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Returns the person's birth chart" className={cn(INPUT, "text-xs")} />
        {error && <p role="alert" className="text-xs text-danger">{error}</p>}
        <button type="button" onClick={add} disabled={!name.trim()} className={cn(BTN_SECONDARY, "min-h-8 w-full")}>
          Add tool
        </button>
      </div>
    </details>
  );
}
