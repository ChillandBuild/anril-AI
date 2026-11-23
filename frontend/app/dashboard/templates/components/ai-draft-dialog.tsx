"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowUpRight, Check, KeyRound, Loader2, Sparkles, X } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { LANGUAGES } from "../types";
import type { Button } from "../types";
import type { TemplatePrefill } from "../template-prefill";

type Category = "MARKETING" | "UTILITY";
type KeyStatus = { is_set: boolean; display_value: string };

const IDEAS = [
  "Remind customers their payment is due, with a Pay now link",
  "Tell old customers about our new collection with a 10% offer",
  "Ask happy customers for a Google review",
  "Confirm a booking with the date and time",
];

type Draft = {
  name: string;
  category: Category;
  language: string;
  header_text?: string;
  body_text: string;
  footer_text?: string;
  buttons?: Button[];
};

/** FastAPI sends `detail` as text, or as {code, message} for "no key yet". */
function readError(body: unknown, fallback: string): { message: string; noKey: boolean } {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object") {
    const d = detail as { code?: string; message?: string };
    return { message: d.message || fallback, noKey: d.code === "template_ai_key_missing" };
  }
  return { message: typeof detail === "string" ? detail : fallback, noKey: false };
}

/**
 * "Write with AI": the owner says in their own words what the message is for, Anril's AI drafts
 * it, and the Create Template builder opens filled in. It runs on its own AI key, set up right
 * here. Nothing is saved or sent to Meta here: the owner checks the draft in the builder first.
 */
export default function AiDraftDialog({
  open,
  onClose,
  onDrafted,
}: {
  open: boolean;
  onClose: () => void;
  onDrafted: (p: TemplatePrefill) => void;
}) {
  const [keyStatus, setKeyStatus] = useState<KeyStatus | null>(null);
  const [view, setView] = useState<"loading" | "key" | "write">("loading");
  const [keyInput, setKeyInput] = useState("");
  const [idea, setIdea] = useState("");
  const [category, setCategory] = useState<Category | "AUTO">("AUTO");
  const [language, setLanguage] = useState("en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const keyBox = useRef<HTMLInputElement>(null);

  // Each time it opens: is there a key yet?
  useEffect(() => {
    if (!open) return;
    let live = true;
    setError(null);
    setView("loading");
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/templates/ai-key`, { headers: await getAuthHeaders() });
        const body = await res.json().catch(() => null);
        if (!res.ok) throw new Error(readError(body, "Couldn't check the AI key. Please try again.").message);
        if (!live) return;
        setKeyStatus(body as KeyStatus);
        setView((body as KeyStatus).is_set ? "write" : "key");
      } catch (e) {
        if (!live) return;
        setError(e instanceof Error ? e.message : "Couldn't check the AI key.");
        setView("write");
      }
    })();
    return () => { live = false; };
  }, [open]);

  useEffect(() => {
    const t = setTimeout(() => (view === "key" ? keyBox.current : box.current)?.focus(), 50);
    return () => clearTimeout(t);
  }, [view]);

  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [open, busy, onClose]);

  if (!open) return null;

  async function saveKey() {
    const k = keyInput.trim();
    if (!k) {
      setError("Paste your AI key first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/v1/templates/ai-key`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await getAuthHeaders()) },
        body: JSON.stringify({ api_key: k }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(readError(body, "Couldn't save the key. Please try again.").message);
      setKeyStatus(body as KeyStatus);
      setKeyInput("");
      setView("write");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the key.");
    } finally {
      setBusy(false);
    }
  }

  async function removeKey() {
    if (!confirm("Remove the Write with AI key? Write with AI stops working until a key is added again.")) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/v1/templates/ai-key`, { method: "DELETE", headers: await getAuthHeaders() });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(readError(body, "Couldn't remove the key.").message);
      setKeyStatus({ is_set: false, display_value: "" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't remove the key.");
    } finally {
      setBusy(false);
    }
  }

  async function draft() {
    const text = idea.trim();
    if (text.length < 8) {
      setError("Say a little more about the message, for example who it is for and what it should say.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/v1/templates/ai-draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await getAuthHeaders()) },
        body: JSON.stringify({ idea: text, category: category === "AUTO" ? null : category, language }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        const err = readError(body, "The AI couldn't write a draft just now. Please try again.");
        if (err.noKey) {
          setKeyStatus({ is_set: false, display_value: "" });
          setView("key");
        }
        throw new Error(err.message);
      }
      const d = body as Draft;
      onDrafted({
        name: d.name,
        category: d.category,
        language: d.language || language,
        headerType: d.header_text ? "TEXT" : "NONE",
        headerText: d.header_text ?? "",
        bodyText: d.body_text,
        footerText: d.footer_text ?? "",
        buttons: d.buttons ?? [],
        source: "Written with AI. Check the words and any link, then send it to Meta.",
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "The AI couldn't write a draft just now.");
    } finally {
      setBusy(false);
    }
  }

  const keySet = !!keyStatus?.is_set;

  return (
    <div className="fixed inset-0 z-dialog flex items-end justify-center bg-black/40 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={() => !busy && onClose()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="ai-draft-title"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg animate-slide-up rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl"
      >
        <div className="flex items-start justify-between gap-3 border-b border-[#f1f5f9] px-5 pb-4 pt-5">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-primary-50 to-[#fdf4e3] text-primary">
              {view === "key" ? <KeyRound size={18} /> : <Sparkles size={18} />}
            </span>
            <div>
              <h2 id="ai-draft-title" className="font-display text-base font-bold text-ink">
                {view === "key" ? "Set up AI key" : "Write with AI"}
              </h2>
              <p className="text-[12.5px] text-ink-muted">
                {view === "key"
                  ? "Write with AI uses its own Google AI key, kept apart from your chat AI."
                  : "Say what the message is for. You check it before it goes to Meta."}
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={busy} aria-label="Close" className="rounded-lg p-1.5 text-ink-muted hover:bg-[#f8fafc] hover:text-ink">
            <X size={16} />
          </button>
        </div>

        {view === "loading" && (
          <div className="flex items-center justify-center gap-2 px-5 py-12 text-sm text-ink-muted">
            <Loader2 size={16} className="animate-spin" /> Checking your AI key…
          </div>
        )}

        {view === "key" && (
          <div className="space-y-4 px-5 py-4">
            {keySet && (
              <div className="flex items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50/70 px-3 py-2.5">
                <span className="flex min-w-0 items-center gap-2 text-[13px] text-emerald-800">
                  <Check size={14} className="shrink-0" />
                  <span className="truncate">Key in use: <span className="font-mono font-semibold">{keyStatus?.display_value}</span></span>
                </span>
                <button type="button" onClick={removeKey} disabled={busy} className="shrink-0 text-[12.5px] font-semibold text-red-600 hover:underline">
                  Remove
                </button>
              </div>
            )}
            <ol className="space-y-1.5 text-[13px] text-ink-secondary">
              <li>
                1. Open{" "}
                <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 font-semibold text-primary hover:underline">
                  Google AI Studio <ArrowUpRight size={12} />
                </a>{" "}
                and click Create API key.
              </li>
              <li>2. Copy the key and paste it below. Anril checks it with Google before saving.</li>
            </ol>
            <div>
              <label htmlFor="ai-key" className="mb-1.5 block text-[13px] font-semibold text-ink">
                {keySet ? "New AI key" : "AI key"}
              </label>
              <input
                id="ai-key"
                ref={keyBox}
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") saveKey(); }}
                placeholder="AIza…"
                className="h-11 w-full rounded-xl border border-[#e2e8f0] px-3 font-mono text-[14px] text-ink placeholder:text-[#94a3b8] focus:border-primary-300 focus:outline-none focus:ring-2 focus:ring-primary-100"
              />
              <p className="mt-1.5 text-[12px] text-ink-muted">Saved for this business only and never shown in full again. Google bills this key for the drafts it writes.</p>
            </div>
          </div>
        )}

        {view === "write" && (
          <div className="space-y-4 px-5 py-4">
            <div>
              <label htmlFor="ai-idea" className="mb-1.5 block text-[13px] font-semibold text-ink">What should the message say?</label>
              <textarea
                id="ai-idea"
                ref={box}
                value={idea}
                onChange={(e) => setIdea(e.target.value)}
                rows={3}
                maxLength={600}
                placeholder="e.g. Remind customers their balance is due, with a Pay now link"
                className="w-full resize-none rounded-xl border border-[#e2e8f0] px-3 py-2.5 text-[14px] text-ink placeholder:text-[#94a3b8] focus:border-primary-300 focus:outline-none focus:ring-2 focus:ring-primary-100"
              />
              <div className="mt-2 flex flex-wrap gap-1.5">
                {IDEAS.map((i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setIdea(i)}
                    className="rounded-full border border-[#e7e2da] bg-[#faf8f5] px-2.5 py-1 text-[12px] text-[#475569] transition hover:border-primary-200 hover:text-primary"
                  >
                    {i}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <span className="mb-1.5 block text-[13px] font-semibold text-ink">Type</span>
                <Select
                  aria-label="Template type"
                  value={category}
                  onChange={(v) => setCategory(v as Category | "AUTO")}
                  options={[
                    { value: "AUTO", label: "Let AI pick" },
                    { value: "MARKETING", label: "Marketing" },
                    { value: "UTILITY", label: "Utility" },
                  ]}
                />
              </div>
              <div>
                <span className="mb-1.5 block text-[13px] font-semibold text-ink">Language</span>
                <Select
                  aria-label="Language"
                  value={language}
                  onChange={setLanguage}
                  options={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
                />
              </div>
            </div>
          </div>
        )}

        {error && (
          <p className="mx-5 mb-4 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">
            <AlertCircle size={14} className="mt-0.5 shrink-0" /> {error}
          </p>
        )}

        <div className="flex items-center justify-between gap-2 border-t border-[#f1f5f9] px-5 py-4">
          <div className="min-w-0 text-[12px] text-ink-muted">
            {view === "write" && keySet && (
              <button type="button" onClick={() => { setError(null); setView("key"); }} className="inline-flex min-w-0 items-center gap-1 hover:text-primary">
                <KeyRound size={12} className="shrink-0" />
                <span className="truncate">AI key <span className="font-mono">{keyStatus?.display_value}</span> · Change</span>
              </button>
            )}
            {view === "write" && !keySet && keyStatus && (
              <button type="button" onClick={() => setView("key")} className="font-semibold text-primary hover:underline">Set up AI key ›</button>
            )}
            {view === "key" && keySet && (
              <button type="button" onClick={() => { setError(null); setView("write"); }} className="font-semibold text-primary hover:underline">‹ Back to writing</button>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button type="button" onClick={onClose} disabled={busy} className="btn-ghost text-sm">Cancel</button>
            {view === "key" && (
              <button
                type="button"
                onClick={saveKey}
                disabled={busy}
                className="flex h-10 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white shadow-md transition hover:bg-primary/90 disabled:opacity-60"
              >
                {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
                {busy ? "Checking…" : "Check and save"}
              </button>
            )}
            {view === "write" && (
              <button
                type="button"
                onClick={draft}
                disabled={busy}
                className="flex h-10 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white shadow-md transition hover:bg-primary/90 disabled:opacity-60"
              >
                {busy ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                {busy ? "Writing…" : "Write my draft"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
