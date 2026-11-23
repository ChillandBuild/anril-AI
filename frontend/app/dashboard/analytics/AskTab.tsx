"use client";

import { useState } from "react";
import Link from "next/link";
import { Sparkles } from "lucide-react";
import { MiniChart } from "@/components/analytics/MiniChart";
import { askQuestion, cleanChart, safeLinks, type AskResult } from "@/lib/reportsApi";
import { ErrorBox } from "./reportsUi";

export function AskTab() {
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [result, setResult] = useState<AskResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim() || asking) return;
    setAsking(true);
    setError(null);
    setResult(null);
    try {
      setResult(await askQuestion(question.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't get an answer. Try again.");
    } finally {
      setAsking(false);
    }
  }

  const chart = cleanChart(result?.chart);
  const links = safeLinks(result?.links);

  return (
    <div className="rounded-2xl border border-surface-mid/80 bg-white/95 p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-50 text-primary-700 ring-1 ring-primary-100">
          <Sparkles size={13} />
        </span>
        <h2 className="font-label text-sm font-bold text-on-surface">Ask a question</h2>
      </div>
      <p className="mb-3 font-label text-xs text-[#556274]">Ask in Tamil, Tanglish or English. You get the answer in the same way.</p>
      <form onSubmit={handleAsk} className="flex flex-col gap-2 sm:flex-row">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          aria-label="Your question"
          placeholder="e.g. How many hot chats came from Instagram this week?"
          className="h-11 min-w-0 flex-1 rounded-xl border border-surface-mid bg-surface-low px-3 font-body text-sm outline-none focus:border-primary"
        />
        <button
          type="submit"
          disabled={asking || !question.trim()}
          className="h-11 rounded-xl bg-primary px-5 font-label text-sm font-bold text-white transition-colors hover:bg-primary/90 disabled:opacity-40"
        >
          {asking ? "Asking…" : "Ask"}
        </button>
      </form>
      {error && <div className="mt-3"><ErrorBox message={error} /></div>}
      {result && (
        <div className="mt-3 space-y-3 rounded-xl bg-surface-low p-3">
          <p className="whitespace-pre-wrap font-body text-sm text-on-surface">{result.answer}</p>
          {chart && <MiniChart chart={chart} />}
          {links.length > 0 && (
            <div data-print-hide className="flex flex-wrap gap-2">
              {links.map((l) => (
                <Link key={l.href + l.label} href={l.href} className="rounded-xl bg-white px-3 py-2 font-label text-xs font-bold text-primary ring-1 ring-primary-200 hover:bg-primary-50">
                  {l.label}
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
