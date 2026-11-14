"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeftRight, Loader2, Wrench } from "lucide-react";
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
  type TestChatMessage,
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
  saveMemoryResult,
  sourcesSetting,
  suggestionsFor,
  usedLine,
} from "@/components/agents/playground";
import { CharacterSelect } from "@/components/agents/CharacterSelect";
import { Hero, PromptBox, chipClass } from "@/components/agents/PlaygroundParts";
import { TestPersonChips, useTestPeople } from "@/components/agents/TestPersonChips";
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
  used?: CompanionReply["used"];
  trace: string[];
  /** A saved reply from "Earlier chat": no time, model or trace, and no "Try again". */
  earlier?: boolean;
  /** Why the AI call failed (owner-only), e.g. "Your Google AI Studio credits are used up...". */
  problem?: string | null;
};
type Bubble = { kind: "user"; text: string } | ReplyBubble | { kind: "error"; text: string };

/** A paused turn. `trace` = the lines from before the pause; /continue returns none, so they are kept here. */
type PendingTools = { turnId: string; calls: CompanionToolCall[]; started: number; trace: string[] };

/** "Use for <name>": idle, asking "are you sure", or saving. */
type UseFor = "idle" | "confirm" | "saving";
type SaveNote = { tone: "ok" | "info" | "error"; text: string; seeThem: boolean };

const BAR = "mx-auto mt-2 flex max-w-[720px] flex-wrap items-center justify-between gap-2 rounded-[10px] px-2.5 py-2 text-[12.5px]";
const SMALL_BTN = "min-h-8 px-3 text-[12.5px]";
const PERSON_KEY = "pg-person";

function readPerson(): string | null {
  try {
    return window.sessionStorage.getItem(PERSON_KEY);
  } catch {
    return null;
  }
}

function rememberPerson(id: string | null) {
  try {
    if (id) window.sessionStorage.setItem(PERSON_KEY, id);
    else window.sessionStorage.removeItem(PERSON_KEY);
  } catch {
    /* private mode: just don't remember */
  }
}

/** A saved reply as a bubble. Example: { text: "Hello", mood: "warm" } -> shows "Hello" with "warm" under it. */
function earlierReply(m: TestChatMessage): ReplyBubble {
  return { kind: "reply", text: m.text, mood: m.mood, ms: 0, model: null, basis: m.basis, sources: m.sources, trace: [], earlier: true };
}

/**
 * Chat with one character as the owner or as a test customer. Example: the owner types
 * "Which plan am I on?" and Maya answers, with a line under the reply saying what she used
 * ("Used: Its notes about you + 2 past chats · Not from your files"). Coming back later, the saved
 * chat shows first under "Earlier chat". With a started chat the list fills the screen and the
 * input stays at the bottom. The model chip starts on Maya's saved model; trying
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
  tools,
  techLines,
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
  /** Pretend app tools, edited in Advanced. */
  tools: CompanionAppTool[];
  /** Show the grey "what was searched" lines under each reply. */
  techLines: boolean;
}) {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<PendingTools | null>(null);
  const [history, setHistory] = useState<TestChatMessage[]>([]);   // the saved chat, shown under "Earlier chat"
  const [pick, setPick] = useState<string | null>(null);   // null = the character's own model
  const [useFor, setUseFor] = useState<UseFor>("idle");
  const [useForError, setUseForError] = useState("");
  const [savedModel, setSavedModel] = useState("");
  const [compare, setCompare] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  // Who the owner is testing as. null = You.
  const { people, setPeople, max, error: peopleError } = useTestPeople();
  const [personId, setPersonId] = useState<string | null>(null);
  const [restored, setRestored] = useState(false);   // the remembered person has been looked up
  const choosePerson = (id: string | null) => {
    setPersonId(id);
    rememberPerson(id);
  };
  const [epoch, setEpoch] = useState(0);   // bumped by Start over so the screen clears even though the id is the same
  const you = people?.find((p) => p.is_you);
  const person: TestPerson | undefined = people?.find((p) => p.external_user_id === personId) ?? you;

  const [memory, setMemory] = useState<CompanionMemoryStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveNote, setSaveNote] = useState<SaveNote | null>(null);

  // A reply that arrives for another character, person or cleared screen is dropped.
  const screenKey = `${character.id}|${person?.external_user_id ?? ""}|${epoch}`;
  const activeKey = useRef(screenKey);
  const sentHere = useRef(false);   // a message was sent on this screen, so a late "Earlier chat" would repeat it

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [bubbles, pending, history, busy]);

  // This browser tab remembers who you were chatting as; unknown or gone -> You.
  useEffect(() => {
    if (!people || restored) return;
    const stored = readPerson();
    if (stored && people.some((p) => p.external_user_id === stored)) setPersonId(stored);
    setRestored(true);
  }, [people, restored]);

  // A different character or person starts a fresh screen (what they remember stays on the server).
  useEffect(() => {
    activeKey.current = screenKey;
    setBubbles([]);
    setHistory([]);
    sentHere.current = false;
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

  // The saved chat comes back. Typing is never blocked; a failure just leaves the chat empty.
  useEffect(() => {
    const id = person?.external_user_id;
    if (!id || !restored) return;
    const forKey = screenKey;
    companionsApi
      .testPersonChat(character.id, id)
      .then((r) => {
        if (activeKey.current === forKey && !sentHere.current) setHistory(r.messages);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload only when the screen changes
  }, [screenKey, restored]);

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
    used: reply.used,
    trace: [...priorTrace, ...(reply.trace ?? [])],
    problem: reply.problem ?? null,
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

  /** `retry` = "Try again": the server drops the newest question + answer first, and the same pair on screen is replaced. */
  const send = async (given?: string, retry = false) => {
    const message = (given ?? text).trim();
    if (!message || busy || pending) return;
    const forKey = screenKey;
    if (!retry) setText("");
    setBusy(true);
    setSaveNote(null);
    sentHere.current = true;
    setBubbles((b) => [...(retry ? b.slice(0, -2) : b), { kind: "user", text: message }]);
    const started = performance.now();
    const base = {
      model: trying ? pick : undefined,   // the character's own model is what the server uses anyway
      settings: sourcesSetting(sources, live),
      test_person: person && !person.is_you ? person.external_user_id : undefined,
    };
    // Compare: the same message again, without memory, in parallel. Shown beside the first, labelled.
    const [main, bare] = await Promise.allSettled([
      companionsApi.testChat(character.id, message, { ...base, tools, ...(retry ? { retry: true } : {}) }),
      compare && !retry ? companionsApi.testChat(character.id, message, { ...base, use_memory: false }) : Promise.resolve(null),
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

  const started = bubbles.length > 0 || history.length > 0 || !!pending;
  const choices = modelChoices(models, character.model, character.name);
  const tried = pick ? modelLabel(models, pick) : "";
  const own = modelLabel(models, character.model);
  const status = memory ? memoryStatusLine(memory, character) : null;
  const suggestions = suggestionsFor(character);
  const personName = person && !person.is_you ? person.name : null;

  // "Try again" is only for the newest reply of this session: a normal reply right after its question, never a compare pair.
  const last = bubbles[bubbles.length - 1];
  const beforeLast = bubbles[bubbles.length - 2];
  const canRetry = !busy && !pending && last?.kind === "reply" && !last.label && beforeLast?.kind === "user";
  const retryLast = () => {
    if (canRetry && beforeLast?.kind === "user") void send(beforeLast.text, true);
  };

  /** Model "Use for" bars and notes. Above the input once the chat has started, below it on the first screen. */
  const notes = (
    <>
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
    </>
  );

  return (
    // Started: a column as tall as the screen (header + paddings taken off); the list takes the spare height and scrolls, the input stays at the bottom.
    <div className={cn(started && "flex h-[calc(100dvh-10rem)] min-h-[480px] flex-col md:h-[calc(100dvh-13rem)]")}>
      {started ? (
        <div ref={listRef} className="mx-auto mb-2 mt-1 min-h-0 w-full max-w-[720px] flex-1 space-y-3 overflow-y-auto pr-1" aria-live="polite">
          {history.length > 0 && (
            <div className="flex items-center gap-2 text-[11.5px] text-ink-muted" role="separator" aria-label="Earlier chat">
              <span className="h-px flex-1 bg-border-subtle" />
              Earlier chat
              <span className="h-px flex-1 bg-border-subtle" />
            </div>
          )}
          {history.map((m, i) =>
            m.role === "user" ? (
              <UserBubble key={`h${i}`} text={m.text} />
            ) : (
              <ReplyView key={`h${i}`} bubble={earlierReply(m)} techLines={techLines} personName={personName} />
            ),
          )}
          {pairCompareReplies(bubbles).map((b, i) =>
            Array.isArray(b) ? (
              <div key={i} className="grid gap-3 sm:grid-cols-2">
                {/* pairCompareReplies only pairs two replies */}
                <ReplyView bubble={b[0] as ReplyBubble} heading="With memory" full techLines={techLines} personName={personName} />
                <ReplyView bubble={b[1] as ReplyBubble} heading="Without memory" full techLines={techLines} personName={personName} />
              </div>
            ) : b.kind === "user" ? (
              <UserBubble key={i} text={b.text} />
            ) : b.kind === "reply" ? (
              <ReplyView
                key={i}
                bubble={b}
                heading={b.label}
                techLines={techLines}
                personName={personName}
                onRetry={canRetry && b === last ? retryLast : undefined}
              />
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

      {started && <div className="shrink-0">{notes}</div>}
      <div className="shrink-0">
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
              <TestPersonChips
                people={people}
                max={max}
                selectedId={person?.external_user_id ?? ""}
                characterName={character.name}
                onPick={choosePerson}
                onCreated={(p) => {
                  setPeople((list) => [...(list ?? []), p]);
                  choosePerson(p.external_user_id);
                }}
                onStartedOver={(p) => {
                  setPeople((list) => (list ? list.map((x) => (x.external_user_id === p.external_user_id ? p : x)) : list));
                  setEpoch((n) => n + 1);
                }}
                onDeleted={(p) => {
                  setPeople((list) => (list ? list.filter((x) => x.external_user_id !== p.external_user_id) : list));
                  if (person?.external_user_id === p.external_user_id) choosePerson(null);
                }}
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
      </div>

      {!started && notes}

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
    </div>
  );
}

/** A message the owner (or test customer) sent. */
function UserBubble({ text }: { text: string }) {
  return (
    <div className="ml-auto w-fit max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-sm text-white">
      {text}
    </div>
  );
}

/**
 * One answer: the text, a plain "Used:" line (what it drew on), and mood / model / time with "Try again".
 * Example: "Used: Its notes about Meena · From Main resource, p. 12". The grey "what was searched" lines
 * show only when "Show technical lines" is on in Advanced. A saved reply (`earlier`) shows its mood only.
 */
function ReplyView({
  bubble: b,
  heading,
  full,
  techLines,
  personName,
  onRetry,
}: {
  bubble: ReplyBubble;
  heading?: string;
  full?: boolean;
  techLines: boolean;
  /** The test customer's name; null = the owner. */
  personName: string | null;
  /** Given only for the newest reply of this session. */
  onRetry?: () => void;
}) {
  const used = usedLine(b.used, b.basis, b.sources, personName);
  const meta = (b.earlier ? [b.mood] : [b.mood, b.model, formatMs(b.ms)]).filter(Boolean).join(" · ");
  return (
    <div className={cn("min-w-0 space-y-1.5", full ? "w-full" : "max-w-[85%]")}>
      {heading && <div className="text-xs font-medium text-ink-secondary">{heading}</div>}
      <div className="whitespace-pre-wrap rounded-2xl rounded-bl-md bg-surface-mid px-3.5 py-2 text-sm text-ink">{b.text}</div>
      {b.problem && (
        <div role="alert" className="flex gap-1.5 rounded-lg border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs text-red-900">
          <AlertTriangle size={14} aria-hidden="true" className="mt-px shrink-0" />
          <span>
            <span className="font-semibold">Only you see this:</span> {b.problem} Visitors get the sorry line above.
          </span>
        </div>
      )}
      {used && (
        <div className="px-1 text-xs text-ink-secondary">
          <span className="font-semibold">Used:</span> {used}
        </div>
      )}
      {techLines && b.trace.length > 0 && (
        <ul aria-label="What was searched" className="space-y-0.5 border-l-2 border-primary/20 pl-2 text-xs text-ink-secondary">
          {b.trace.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      )}
      {(meta || onRetry) && (
        <div className="flex flex-wrap items-center gap-x-2 px-1 text-[11px] text-ink-muted">
          {meta && <span>{meta}</span>}
          {onRetry && (
            <button type="button" onClick={onRetry} className="text-[11.5px] font-medium text-primary hover:underline">
              Try again
            </button>
          )}
        </div>
      )}
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
