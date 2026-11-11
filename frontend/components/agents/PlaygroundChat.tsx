"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowLeftRight, User, Wrench, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  companionsApi,
  type Companion,
  type CompanionAppTool,
  type CompanionModel,
  type CompanionReply,
  type CompanionToolCall,
  type PlaygroundDefaults,
} from "@/lib/api";
import {
  chatErrorText,
  formatMs,
  formatSetting,
  formatToolCall,
  pairCompareReplies,
  parseToolOutput,
  replySourceLine,
  settingsToSend,
  toolNameError,
} from "@/components/agents/playground";
import { CharacterSelect } from "@/components/agents/CharacterSelect";
import { Hero, PromptBox, chipClass } from "@/components/agents/PlaygroundParts";
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

const SUGGESTIONS = ["What do you know about me?", "What did I tell you last time?", "What do your files say about returns?"];

/**
 * Chat with one character as the owner ("Testing as you"). Example: the owner types
 * "Which plan am I on?" and Maya answers, with grey lines under the reply saying what she
 * searched ("Memory card: 6 lines"); if she asks the app for get_account(...), the owner
 * types the answer by hand or skips.
 */
export function PlaygroundChat({
  character,
  characters,
  onSelectCharacter,
  settings,
  live,
  models,
  liveModel,
  onMessageSent,
}: {
  character: Companion;
  characters: Companion[];
  onSelectCharacter: (id: string) => void;
  settings: PlaygroundDefaults;
  live: PlaygroundDefaults;
  models: CompanionModel[];
  liveModel: string | null;
  /** Tells the page the last typed message, for the REQUEST block. */
  onMessageSent: (message: string) => void;
}) {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<PendingTools | null>(null);
  const [tools, setTools] = useState<CompanionAppTool[]>([]);
  const [model, setModel] = useState("");   // "" = the business's live model
  const [compare, setCompare] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const activeId = useRef(character.id);   // the character on screen now; a reply for another one is dropped

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [bubbles, pending]);

  // A different character starts a fresh screen (its memory of the owner stays on the server).
  useEffect(() => {
    activeId.current = character.id;
    setBubbles([]);
    setPending(null);
    setBusy(false);
  }, [character.id]);

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
    if (reply.status === "tool_call" && reply.turn_id) {
      setPending({ turnId: reply.turn_id, calls: reply.tool_calls, started, trace: [...priorTrace, ...(reply.trace ?? [])] });
      return;
    }
    setPending(null);
    setBubbles((b) => [...b, toBubble(reply, started, undefined, priorTrace)]);
  };

  const send = async (given?: string) => {
    const message = (given ?? text).trim();
    if (!message || busy || pending) return;
    const forId = character.id;
    setText("");
    setBusy(true);
    onMessageSent(message);
    setBubbles((b) => [...b, { kind: "user", text: message }]);
    const started = performance.now();
    const picked = model || undefined;
    const sent = settingsToSend(settings, live);
    // Compare: the same message again, without memory, in parallel. Shown beside the first, labelled.
    const [main, bare] = await Promise.allSettled([
      companionsApi.testChat(character.id, message, { tools, model: picked, settings: sent }),
      compare ? companionsApi.testChat(character.id, message, { model: picked, use_memory: false, settings: sent }) : Promise.resolve(null),
    ]);
    if (activeId.current !== forId) return;   // the owner switched characters meanwhile
    if (main.status === "fulfilled") handle(main.value, started);
    else setBubbles((b) => [...b, { kind: "error", text: chatErrorText(main.reason) }]);
    if (bare.status === "fulfilled" && bare.value) handle(bare.value, started, "Without memory");
    else if (bare.status === "rejected") setBubbles((b) => [...b, { kind: "error", text: `Without memory: ${chatErrorText(bare.reason)}` }]);
    setBusy(false);
  };

  const answerTools = async (results: { id: string; output: unknown }[]) => {
    if (!pending) return;
    const forId = character.id;
    setBusy(true);
    try {
      const reply = await companionsApi.continueTestChat(pending.turnId, results);
      if (activeId.current === forId) handle(reply, pending.started, undefined, pending.trace);
    } catch (err) {
      if (activeId.current !== forId) return;
      setPending(null);
      setBubbles((b) => [...b, { kind: "error", text: chatErrorText(err) }]);
    } finally {
      if (activeId.current === forId) setBusy(false);
    }
  };

  const started = bubbles.length > 0 || !!pending;
  const liveLabel = models.find((m) => m.id === liveModel)?.label;

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
              <label className={chipClass()}>
                <span className="sr-only">Model</span>
                <select value={model} onChange={(e) => setModel(e.target.value)} className="max-w-[190px] cursor-pointer bg-transparent focus:outline-none">
                  <option value="">{liveLabel ? `${liveLabel} (live)` : "Live model"}</option>
                  {models
                    .filter((m) => m.id !== liveModel)
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                      </option>
                    ))}
                </select>
              </label>
            )}
            <span className={chipClass(true)}>{formatSetting("mode", settings.mode)}</span>
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
            <span className="inline-flex items-center gap-1.5 text-ink-secondary">
              <User size={14} aria-hidden="true" /> Testing as you
            </span>
          </>
        }
      />
      {model && <p className="mx-auto mt-2 max-w-[720px] text-xs text-ink-muted">Test chat only; live replies keep the live model.</p>}

      {!started && (
        <div className="mx-auto mt-3.5 flex max-w-[720px] flex-col gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              disabled={busy}
              onClick={() => void send(s)}
              className="rounded-xl border border-border bg-white px-3 py-2.5 text-sm text-ink transition-colors hover:bg-surface-mid disabled:opacity-50"
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
