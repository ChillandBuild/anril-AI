"use client";
import { useEffect, useRef, useState } from "react";
import { Send, Wrench, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  companionsApi,
  type Companion,
  type CompanionAppTool,
  type CompanionModel,
  type CompanionReply,
  type CompanionToolCall,
} from "@/lib/api";
import { chatErrorText, formatMs, formatToolCall, parseToolOutput, replySourceLine, toolNameError } from "@/components/agents/playground";
import { BTN_PRIMARY, BTN_SECONDARY, CARD, INPUT } from "@/components/agents/ui";

type Bubble =
  | { kind: "user"; text: string }
  | { kind: "reply"; text: string; mood: string | null; ms: number; model: string | null; label?: string; basis?: CompanionReply["basis"]; sources?: CompanionReply["sources"] }
  | { kind: "error"; text: string };

type PendingTools = { turnId: string; calls: CompanionToolCall[]; started: number };

/**
 * Chat with one character as the Test person. Example: the owner types
 * "Which plan am I on?" and Maya answers; if it asks the app for
 * get_account(...), the owner types the answer by hand or skips.
 */
export function PlaygroundChat({ character }: { character: Companion }) {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<PendingTools | null>(null);
  const [tools, setTools] = useState<CompanionAppTool[]>([]);
  const [models, setModels] = useState<CompanionModel[]>([]);
  const [liveModel, setLiveModel] = useState<string | null>(null);
  const [model, setModel] = useState("");   // "" = the business's live model
  const [compare, setCompare] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    companionsApi
      .models()
      .then((r) => {
        setModels(r.models);
        setLiveModel(r.default);
      })
      .catch(() => setModels([]));   // the picker just hides; chat still works on the live model
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [bubbles, pending]);

  // A different character starts a fresh screen (its memory of the Test person stays on the server).
  useEffect(() => {
    setBubbles([]);
    setPending(null);
  }, [character.id]);

  const handle = (reply: CompanionReply, started: number, label?: string) => {
    if (label) {
      setBubbles((b) => [
        ...b,
        { kind: "reply", text: reply.text ?? "", mood: reply.mood, ms: performance.now() - started, model: reply.model ?? null, label, basis: reply.basis ?? null, sources: reply.sources ?? [] },
      ]);
      return;
    }
    if (reply.status === "tool_call" && reply.turn_id) {
      setPending({ turnId: reply.turn_id, calls: reply.tool_calls, started });
      return;
    }
    setPending(null);
    setBubbles((b) => [
      ...b,
      { kind: "reply", text: reply.text ?? "", mood: reply.mood, ms: performance.now() - started, model: reply.model ?? null, basis: reply.basis ?? null, sources: reply.sources ?? [] },
    ]);
  };

  const send = async () => {
    const message = text.trim();
    if (!message || busy || pending) return;
    setText("");
    setBusy(true);
    setBubbles((b) => [...b, { kind: "user", text: message }]);
    const started = performance.now();
    const picked = model || undefined;
    // Compare: the same message again, without memory, in parallel. Shown second, labelled.
    const [main, bare] = await Promise.allSettled([
      companionsApi.testChat(character.id, message, { tools, model: picked }),
      compare ? companionsApi.testChat(character.id, message, { model: picked, use_memory: false }) : Promise.resolve(null),
    ]);
    if (main.status === "fulfilled") handle(main.value, started);
    else setBubbles((b) => [...b, { kind: "error", text: chatErrorText(main.reason) }]);
    if (bare.status === "fulfilled" && bare.value) handle(bare.value, started, "Without memory");
    else if (bare.status === "rejected") setBubbles((b) => [...b, { kind: "error", text: `Without memory: ${chatErrorText(bare.reason)}` }]);
    setBusy(false);
  };

  const answerTools = async (results: { id: string; output: unknown }[]) => {
    if (!pending) return;
    setBusy(true);
    try {
      handle(await companionsApi.continueTestChat(pending.turnId, results), pending.started);
    } catch (err) {
      setPending(null);
      setBubbles((b) => [...b, { kind: "error", text: chatErrorText(err) }]);
    } finally {
      setBusy(false);
    }
  };

  const last = [...bubbles].reverse().find((b) => b.kind === "reply" && !b.label) as Extract<Bubble, { kind: "reply" }> | undefined;
  const liveLabel = models.find((m) => m.id === liveModel)?.label;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
      <div className={cn(CARD, "flex min-h-[460px] flex-col p-0")}>
        <div className="border-b border-border-subtle px-4 py-2.5 text-xs text-ink-muted">
          You are chatting as <span className="font-medium text-ink">Test person</span>. Test chats never mix with real customers.
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
          {bubbles.length === 0 && !pending && (
            <p className="py-10 text-center text-sm text-ink-muted">Say hello to {character.name}, e.g. &ldquo;Hi! What can you help me with?&rdquo;</p>
          )}
          {bubbles.map((b, i) =>
            b.kind === "user" ? (
              <div key={i} className="ml-auto max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-sm text-white">
                {b.text}
              </div>
            ) : b.kind === "reply" ? (
              <div key={i} className="max-w-[80%] space-y-1">
                {b.label && <div className="text-[11px] font-medium uppercase tracking-wide text-ink-muted">{b.label}</div>}
                <div className="whitespace-pre-wrap rounded-2xl rounded-bl-md bg-surface-mid px-3.5 py-2 text-sm text-ink">{b.text}</div>
                {replySourceLine(b.basis, b.sources) && <div className="px-1 text-xs text-ink-secondary">{replySourceLine(b.basis, b.sources)}</div>}
              </div>
            ) : (
              <div key={i} role="alert" className="max-w-[80%] rounded-xl border border-danger/20 bg-danger/5 px-3.5 py-2 text-sm text-danger">
                {b.text}
              </div>
            ),
          )}
          {pending && <ToolAnswer calls={pending.calls} busy={busy} onAnswer={answerTools} />}
          {busy && !pending && <div className="text-xs text-ink-muted">{character.name} is typing…</div>}
          <div ref={endRef} />
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border-subtle px-3 pt-3 text-xs text-ink-secondary">
          {models.length > 0 && (
            <label className="flex items-center gap-1.5">
              <span>Model</span>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="rounded-lg border border-border bg-white px-2 py-1 text-xs text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15"
              >
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
          <label className="flex items-center gap-1.5" title="Also answer without remembered facts or chat history, side by side">
            <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} className="h-3.5 w-3.5 accent-primary" />
            Compare without memory
          </label>
          {model && <span className="text-ink-muted">Test chat only; live replies keep the live model.</span>}
        </div>
        <form
          className="flex items-end gap-2 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <label htmlFor="playground-message" className="sr-only">Message</label>
          <textarea
            id="playground-message"
            rows={1}
            value={text}
            maxLength={4000}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder={pending ? "Answer the tool first" : `Message ${character.name}`}
            disabled={!!pending}
            className={cn(INPUT, "min-h-10 resize-none")}
          />
          <button type="submit" disabled={busy || !!pending || !text.trim()} className={cn(BTN_PRIMARY, "h-10 px-3")} aria-label="Send">
            <Send size={16} aria-hidden="true" />
          </button>
        </form>
      </div>

      <aside className="space-y-4">
        <section className={CARD} aria-labelledby="this-reply">
          <h2 id="this-reply" className="mb-2 text-sm font-semibold text-ink">This reply</h2>
          {last ? (
            <dl className="space-y-1.5 text-sm">
              <Row label="Mood" value={last.mood ?? "—"} />
              <Row label="Model" value={last.model ?? "Your Anril AI model"} />
              <Row label="Reply time" value={formatMs(last.ms)} />
            </dl>
          ) : (
            <p className="text-sm text-ink-muted">Send a message to see its mood, model and time.</p>
          )}
        </section>
        <AppTools tools={tools} onChange={setTools} />
      </aside>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="truncate font-medium capitalize text-ink">{value}</dd>
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

/** Tools the business's app would offer, so the owner can test tool calls without their app. */
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
    <section className={CARD} aria-labelledby="app-tools">
      <h2 id="app-tools" className="text-sm font-semibold text-ink">Your app&apos;s tools</h2>
      <p className="mb-3 mt-1 text-xs text-ink-muted">Optional. Pretend your app offers these; you answer them by hand.</p>
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
    </section>
  );
}
