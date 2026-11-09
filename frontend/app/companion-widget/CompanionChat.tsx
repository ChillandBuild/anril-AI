"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://aira-ai-5tfr.onrender.com";
const BASE = `${API_URL}/api/v1/companion/widget`;
const TOOL_WAIT_MS = 90_000; // the server keeps a paused turn for 2 minutes

type Auth = { companion_id: string; user_id: string; exp: number; signature: string };
type Msg = { role: "user" | "assistant"; content: string; mood?: string | null };
type ToolCall = { id: string; name: string; args: Record<string, unknown> };
type Reply = {
  status: "done" | "tool_call";
  text?: string | null;
  mood?: string | null;
  turn_id?: string | null;
  tool_calls?: ToolCall[];
};

const MOOD_FACE: Record<string, string> = {
  calm: "🙂", warm: "😊", happy: "😄", concerned: "😟", encouraging: "💪", serious: "🧐",
};

const ERRORS: Record<number, string> = {
  401: "Your session has expired. Reload the page to keep chatting.",
  409: "This assistant isn't available yet.",
  429: "You're sending messages quickly. Wait a minute and try again.",
  503: "The assistant is busy right now. Try again in a few seconds.",
};

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new ApiError(res.status, ERRORS[res.status] || "Something went wrong. Try again.");
  }
  return res.json() as Promise<T>;
}

export default function CompanionChat() {
  const params = useSearchParams();
  const companionId = params.get("c") || "";
  const [auth, setAuth] = useState<Auth | null>(null);
  const [name, setName] = useState("Assistant");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [mood, setMood] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [embedded, setEmbedded] = useState(true);

  const parentOrigin = useRef<string | null>(null);
  const displayName = useRef<string | null>(null);
  const tools = useRef<unknown[]>([]);
  const pendingTools = useRef(new Map<string, (results: unknown[]) => void>());
  const listEnd = useRef<HTMLDivElement>(null);

  // Handshake with the loader script on the parent page. The first init from window.parent
  // fixes the parent's origin; later messages must come from that window and origin.
  useEffect(() => {
    if (window.parent === window) {
      setEmbedded(false);
      return;
    }
    function onMessage(event: MessageEvent) {
      if (event.source !== window.parent) return;
      if (parentOrigin.current && event.origin !== parentOrigin.current) return;
      const data = event.data || {};
      if (data.type === "anril:init" && !parentOrigin.current) {
        const a = data.auth as Auth;
        if (!a || a.companion_id !== companionId) return;
        parentOrigin.current = event.origin;
        displayName.current = data.displayName || null;
        tools.current = Array.isArray(data.tools) ? data.tools : [];
        setAuth(a);
      } else if (data.type === "anril:tool_results") {
        const resolve = pendingTools.current.get(data.requestId);
        if (resolve) {
          pendingTools.current.delete(data.requestId);
          resolve(Array.isArray(data.results) ? data.results : []);
        }
      }
    }
    window.addEventListener("message", onMessage);
    window.parent.postMessage({ type: "anril:ready" }, "*");
    return () => window.removeEventListener("message", onMessage);
  }, [companionId]);

  useEffect(() => {
    if (!auth) return;
    call<{ companion: { name: string }; messages: Msg[] }>("/session", auth)
      .then((s) => {
        setName(s.companion.name);
        setMessages(s.messages);
        const last = [...s.messages].reverse().find((m) => m.role === "assistant");
        setMood(last?.mood || null);
      })
      .catch((e: ApiError) => setError(e.message));
  }, [auth]);

  useEffect(() => {
    listEnd.current?.scrollIntoView({ block: "end" });
  }, [messages, busy]);

  const askParentForTools = useCallback((turnId: string, calls: ToolCall[]) => {
    return new Promise<unknown[]>((resolve) => {
      const timer = setTimeout(() => {
        pendingTools.current.delete(turnId);
        resolve(calls.map((c) => ({ id: c.id, output: { error: "timeout" } })));
      }, TOOL_WAIT_MS);
      pendingTools.current.set(turnId, (results) => {
        clearTimeout(timer);
        resolve(results);
      });
      window.parent.postMessage({ type: "anril:tool_calls", requestId: turnId, calls }, parentOrigin.current || "*");
    });
  }, []);

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || !auth || busy) return;
    setDraft("");
    setError(null);
    setMessages((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      let reply = await call<Reply>("/chat", {
        ...auth, message: text, display_name: displayName.current, tools: tools.current,
      });
      while (reply.status === "tool_call" && reply.turn_id) {
        const results = await askParentForTools(reply.turn_id, reply.tool_calls || []);
        reply = await call<Reply>("/chat/continue", { ...auth, turn_id: reply.turn_id, results });
      }
      if (reply.text) setMessages((m) => [...m, { role: "assistant", content: reply.text!, mood: reply.mood }]);
      setMood(reply.mood || null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the assistant. Check your connection.");
    } finally {
      setBusy(false);
    }
  }

  if (!embedded) {
    return (
      <main className="flex min-h-screen items-center justify-center p-6 text-center text-sm text-slate-600">
        This is the Anril companion chat window. Add it to a website with companion-widget.js.
      </main>
    );
  }

  return (
    <main className="flex h-screen flex-col bg-white text-slate-900">
      <header className="flex items-center gap-3 border-b border-slate-200 bg-[var(--primary)] px-4 py-3 text-white">
        <span aria-hidden className="text-2xl">{MOOD_FACE[mood || "calm"] || "🙂"}</span>
        <h1 className="flex-1 truncate text-base font-semibold">{name}</h1>
        <button
          type="button"
          onClick={() => window.parent.postMessage({ type: "anril:close" }, parentOrigin.current || "*")}
          className="rounded px-2 py-1 text-lg leading-none hover:bg-white/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"
          aria-label="Close chat"
        >
          ✕
        </button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4" aria-live="polite">
        {!auth && !error && <p className="text-center text-sm text-slate-500">Connecting…</p>}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <p
              className={
                "max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-[15px] leading-snug " +
                (m.role === "user" ? "bg-[var(--primary)] text-white" : "bg-slate-100 text-slate-900")
              }
            >
              {m.content}
            </p>
          </div>
        ))}
        {busy && <p className="text-sm text-slate-500">{name} is typing…</p>}
        <div ref={listEnd} />
      </div>

      {error && (
        <p role="alert" className="border-t border-red-100 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <form onSubmit={send} className="flex gap-2 border-t border-slate-200 p-3">
        <label htmlFor="companion-input" className="sr-only">
          Message
        </label>
        <input
          id="companion-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          maxLength={4000}
          autoComplete="off"
          placeholder="Type a message…"
          disabled={!auth}
          className="min-w-0 flex-1 rounded-full border border-slate-300 px-4 py-2 text-[15px] focus:border-[var(--primary)] focus:outline-none"
        />
        <button
          type="submit"
          disabled={!auth || busy || !draft.trim()}
          className="rounded-full bg-[var(--primary)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </main>
  );
}
