"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowUpRight,
  Check,
  ChevronDown,
  CornerUpLeft,
  History,
  Loader2,
  Phone,
  RefreshCw,
  Sparkles,
  AlertTriangle,
} from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { LANGUAGES } from "../types";
import type { Button } from "../types";
import type { TemplatePrefill } from "../template-prefill";
import { pushPrompt, readPrompts } from "../ai-writer-model";

/** One draft from POST /api/v1/templates/ai-draft. */
export type AiDraft = {
  name: string;
  category: "MARKETING" | "UTILITY";
  language: string;
  header_text: string;
  body_text: string;
  footer_text: string;
  buttons: Button[];
  approach: string;
  problems: string[];
};

const STYLES = [
  { value: "friendly", label: "Friendly" },
  { value: "festive", label: "Festive" },
  { value: "urgent", label: "Urgent" },
  { value: "formal", label: "Formal" },
];
const GOALS = [
  { value: "clicks", label: "More clicks" },
  { value: "replies", label: "More replies" },
];
const IDEAS = [
  "Remind customers their payment is due, with a Pay now link",
  "Tell old customers about our new collection",
  "Ask happy customers for a Google review",
  "Confirm a booking with the date and time",
];
const MAX_IDEA = 1024;

/** *bold* and {{n}} as WhatsApp shows them. */
function RichText({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\*[^*\n]+\*|\{\{\d+\}\})/g).map((part, i) => {
        if (/^\*[^*\n]+\*$/.test(part)) return <strong key={i}>{part.slice(1, -1)}</strong>;
        if (/^\{\{\d+\}\}$/.test(part)) return <span key={i} className="font-semibold text-[#0b7a75]">{part}</span>;
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}

function ButtonIcon({ type }: { type: string }) {
  if (type === "URL") return <ArrowUpRight size={12} aria-hidden="true" />;
  if (type === "PHONE_NUMBER") return <Phone size={11} aria-hidden="true" />;
  return <CornerUpLeft size={11} aria-hidden="true" />;
}

function DraftCard({ draft, index, onUse, used }: { draft: AiDraft; index: number; onUse: () => void; used: boolean }) {
  const ok = draft.problems.length === 0;
  return (
    <div className={`flex flex-col overflow-hidden rounded-2xl border bg-white shadow-sm transition ${used ? "border-primary ring-2 ring-primary-100" : "border-[#e7e2da]"}`}>
      <div className="flex items-center justify-between gap-2 border-b border-[#f1ede6] px-3.5 py-2.5">
        <span className="font-label text-[13px] font-bold text-ink">Draft {index + 1}</span>
        <span className="truncate rounded-full bg-[#f4f1ec] px-2.5 py-0.5 text-[11.5px] font-medium text-[#475569]">{draft.approach}</span>
      </div>
      <div className="flex-1 space-y-1 bg-[#EFE7DD] p-3">
        <div className="rounded-lg rounded-tl-[3px] bg-white px-2.5 py-2 shadow-[0_1px_0.5px_rgba(11,20,26,.13)]">
          {draft.header_text && <p className="mb-1 text-[13px] font-bold text-[#111B21]">{draft.header_text}</p>}
          <p className="whitespace-pre-wrap break-words text-[13px] leading-[1.45] text-[#111B21]">
            <RichText text={draft.body_text} />
          </p>
          {draft.footer_text && <p className="mt-1 text-[11.5px] text-[#667781]">{draft.footer_text}</p>}
          <p className="mt-0.5 text-right text-[10px] text-[#8696A0]">12:00 PM <span className="text-[#53bdeb]">✓✓</span></p>
        </div>
        {draft.buttons.map((b, i) => (
          <div key={i} className="flex h-8 items-center justify-center gap-1 rounded-lg bg-white text-[13px] font-medium text-[#027eb5] shadow-[0_1px_0.5px_rgba(11,20,26,.13)]">
            <span className="truncate">{b.text}</span>
            <ButtonIcon type={b.type} />
          </div>
        ))}
      </div>
      <div className="space-y-2.5 px-3.5 py-3">
        <p className="text-[12px] text-ink-muted">
          <span className="font-mono">{draft.name}</span> · {draft.category === "UTILITY" ? "Utility" : "Marketing"}
        </p>
        {ok ? (
          <p className="flex items-center gap-1.5 text-[12.5px] font-medium text-emerald-700">
            <Check size={13} aria-hidden="true" /> Passes Meta&apos;s rules
          </p>
        ) : (
          <p className="flex items-start gap-1.5 text-[12.5px] text-amber-800">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span>Needs a fix before sending: {draft.problems.join(" ")}</span>
          </p>
        )}
        <button
          type="button"
          onClick={onUse}
          className={`flex h-9 w-full items-center justify-center gap-1.5 rounded-xl text-sm font-semibold transition ${
            used ? "bg-primary-50 text-primary" : "bg-primary text-white shadow-sm hover:bg-primary/90"
          }`}
        >
          {used ? <><Check size={14} /> In the form below</> : "Use this"}
        </button>
      </div>
    </div>
  );
}

/**
 * Write with AI, at the top of Create Template: the owner says what the message is for, picks a
 * style and goal, and gets three different drafts as WhatsApp bubbles, each checked against Meta's
 * rules. "Use this" fills the form below, which stays fully editable. Nothing is saved or sent.
 */
export default function AiWriter({
  defaultOpen,
  language: builderLanguage,
  onUse,
}: {
  defaultOpen: boolean;
  language: string;
  onUse: (p: TemplatePrefill) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [idea, setIdea] = useState("");
  const [category, setCategory] = useState("AUTO");
  const [language, setLanguage] = useState(builderLanguage || "en");
  const [style, setStyle] = useState("friendly");
  const [goal, setGoal] = useState("clicks");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<AiDraft[]>([]);
  const [usedIndex, setUsedIndex] = useState<number | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => setOpen(defaultOpen), [defaultOpen]);
  useEffect(() => setHistory(readPrompts()), []);
  useEffect(() => {
    if (open) setTimeout(() => box.current?.focus(), 50);
  }, [open]);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/templates/ai-status`, { headers: await getAuthHeaders() });
        const body = await res.json().catch(() => null);
        if (live) setEnabled(res.ok ? !!body?.enabled : null);
      } catch {
        if (live) setEnabled(null); // unknown: let them try, the draft call explains
      }
    })();
    return () => { live = false; };
  }, []);

  async function generate() {
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
        body: JSON.stringify({ idea: text, category: category === "AUTO" ? null : category, language, style, goal }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        const detail = body?.detail;
        if (detail && typeof detail === "object" && detail.code === "template_ai_off") setEnabled(false);
        throw new Error(typeof detail === "string" ? detail : detail?.message || "The AI couldn't write drafts just now. Please try again.");
      }
      setDrafts((body?.drafts ?? []) as AiDraft[]);
      setUsedIndex(null);
      setHistory(pushPrompt(text));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The AI couldn't write drafts just now.");
    } finally {
      setBusy(false);
    }
  }

  function use(d: AiDraft, i: number) {
    setUsedIndex(i);
    onUse({
      name: d.name,
      category: d.category,
      language: d.language,
      headerType: d.header_text ? "TEXT" : "NONE",
      headerText: d.header_text,
      bodyText: d.body_text,
      footerText: d.footer_text,
      buttons: d.buttons,
      source: "",
    });
  }

  return (
    <section className="mb-6 overflow-hidden rounded-2xl border border-primary-200 bg-gradient-to-br from-white via-white to-primary-50/60 shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
      >
        <span className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-white shadow-sm">
            <Sparkles size={16} />
          </span>
          <span>
            <span className="block font-display text-[15px] font-bold text-ink">Write with AI</span>
            <span className="block text-[12.5px] text-ink-muted">Say what the message is for. Get 3 drafts, pick one, edit it below.</span>
          </span>
        </span>
        <ChevronDown size={18} className={`shrink-0 text-ink-muted transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="border-t border-primary-100 px-5 pb-5 pt-4">
          {enabled === false ? (
            <p className="flex items-start gap-2 rounded-xl border border-[#e7e2da] bg-[#faf8f5] px-3.5 py-3 text-[13px] text-[#475569]">
              <AlertCircle size={15} className="mt-0.5 shrink-0 text-ink-muted" />
              Write with AI isn&apos;t switched on for your account yet. Ask Anril support to turn it on. You can still fill in the form below yourself.
            </p>
          ) : (
            <div className="space-y-4">
              <div>
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <label htmlFor="ai-idea" className="text-[13px] font-semibold text-ink">What should the message say?</label>
                  {history.length > 0 && (
                    <div className="relative">
                      <button
                        type="button"
                        onClick={() => setHistoryOpen((v) => !v)}
                        aria-expanded={historyOpen}
                        className="flex items-center gap-1 text-[12px] font-semibold text-primary hover:underline"
                      >
                        <History size={12} /> Previous prompts
                      </button>
                      {historyOpen && (
                        <ul className="absolute right-0 top-6 z-20 w-72 overflow-hidden rounded-xl border border-[#e2e8f0] bg-white py-1 shadow-xl">
                          {history.map((h) => (
                            <li key={h}>
                              <button
                                type="button"
                                onClick={() => { setIdea(h); setHistoryOpen(false); }}
                                className="block w-full truncate px-3 py-2 text-left text-[13px] text-ink hover:bg-[#f8fafc]"
                              >
                                {h}
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
                <textarea
                  id="ai-idea"
                  ref={box}
                  value={idea}
                  onChange={(e) => setIdea(e.target.value.slice(0, MAX_IDEA))}
                  rows={3}
                  placeholder="e.g. Remind customers who left items in their cart, 10% off with code SAVE10 till Sunday"
                  className="w-full resize-y rounded-xl border border-[#e2e8f0] bg-white px-3 py-2.5 text-[14px] text-ink placeholder:text-[#94a3b8] focus:border-primary-300 focus:outline-none focus:ring-2 focus:ring-primary-100"
                />
                <div className="mt-1.5 flex flex-wrap items-start justify-between gap-2">
                  <div className="flex flex-wrap gap-1.5">
                    {IDEAS.map((i) => (
                      <button
                        key={i}
                        type="button"
                        onClick={() => setIdea(i)}
                        className="rounded-full border border-[#e7e2da] bg-white px-2.5 py-1 text-[12px] text-[#475569] transition hover:border-primary-200 hover:text-primary"
                      >
                        {i}
                      </button>
                    ))}
                  </div>
                  <span className="text-[11.5px] tabular-nums text-ink-muted">{idea.length} / {MAX_IDEA}</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <label className="block">
                  <span className="mb-1.5 block text-[13px] font-semibold text-ink">Type</span>
                  <Select
                    aria-label="Template type"
                    value={category}
                    onChange={setCategory}
                    options={[{ value: "AUTO", label: "Let AI pick" }, { value: "MARKETING", label: "Marketing" }, { value: "UTILITY", label: "Utility" }]}
                  />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-[13px] font-semibold text-ink">Language</span>
                  <Select aria-label="Language" value={language} onChange={setLanguage} options={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))} />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-[13px] font-semibold text-ink">Style</span>
                  <Select aria-label="Style" value={style} onChange={setStyle} options={STYLES} />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-[13px] font-semibold text-ink">Goal</span>
                  <Select aria-label="Goal" value={goal} onChange={setGoal} options={GOALS} />
                </label>
              </div>

              {error && (
                <p className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">
                  <AlertCircle size={14} className="mt-0.5 shrink-0" /> {error}
                </p>
              )}

              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-[12px] text-ink-muted">
                  The AI uses what Anril knows about your business. Nothing is sent to Meta until you submit.
                </p>
                <button
                  type="button"
                  onClick={generate}
                  disabled={busy}
                  className="flex h-10 items-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-white shadow-md transition hover:bg-primary/90 disabled:opacity-60"
                >
                  {busy ? <Loader2 size={15} className="animate-spin" /> : drafts.length ? <RefreshCw size={15} /> : <Sparkles size={15} />}
                  {busy ? "Writing 3 drafts…" : drafts.length ? "Write 3 new drafts" : "Write 3 drafts"}
                </button>
              </div>

              {busy && !drafts.length && (
                <div className="grid gap-3 md:grid-cols-3" aria-hidden="true">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="h-64 animate-pulse rounded-2xl bg-[#f1ede6]" />
                  ))}
                </div>
              )}

              {drafts.length > 0 && (
                <div className={`grid gap-3 md:grid-cols-3 ${busy ? "opacity-50" : ""}`}>
                  {drafts.map((d, i) => (
                    <DraftCard key={`${d.name}-${i}`} draft={d} index={i} used={usedIndex === i} onUse={() => use(d, i)} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
