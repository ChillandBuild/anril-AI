"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { PeriodPicker } from "@/components/ai-setup/PeriodPicker";
import { NoAccess, SetupShell, useSetupAccess } from "@/components/ai-setup/SetupShell";
import { aiSetupApi, questionFromSearch, sameQuestion, timesLabel, type CouldntAnswerRow, type Period } from "@/lib/aiSetupApi";

const FIELD =
  "w-full rounded-xl border border-border-subtle bg-white px-3 py-2 font-body text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20";

function when(iso: string) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function AnswerForm({ row, onDone }: { row: CouldntAnswerRow; onDone: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await aiSetupApi.answer(row.question, text.trim());
      toast.success("Saved. The AI agent will use this next time.");
      onDone();
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Could not save. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="mt-3 space-y-2">
      <label className="block font-label text-xs font-bold text-ink">
        The AI agent should say
        <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} rows={3} autoFocus
          className={`${FIELD} mt-1 resize-y font-normal`} placeholder="Type the answer once. It is saved to Teach & offers." />
      </label>
      {error && <p role="alert" className="font-body text-xs text-danger">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || !text.trim()} className="btn-primary min-h-9 disabled:opacity-50">
          {busy && <Loader2 size={14} className="animate-spin" aria-hidden />} Save answer
        </button>
      </div>
    </form>
  );
}

export default function CouldntAnswerPage() {
  const { loading: roleLoading, canView, canEdit } = useSetupAccess();
  const [period, setPeriod] = useState<Period>("30d");
  const [rows, setRows] = useState<CouldntAnswerRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await aiSetupApi.couldntAnswer(period);
      setRows(res.questions);
      setFailed(false);
      const wanted = questionFromSearch(window.location.search);
      if (wanted) {
        const match = res.questions.find((q) => sameQuestion(q.question, wanted));
        if (match) setOpen(match.question);
      }
    } catch {
      setFailed(true);
    }
  }, [period]);

  useEffect(() => {
    if (canView) void load();
  }, [canView, load]);

  if (roleLoading) return <div className="m-6 min-h-[320px] animate-pulse rounded-2xl bg-border-subtle" />;
  if (!canView) return <NoAccess />;

  return (
    <SetupShell
      title="Couldn't answer"
      intro="Questions the AI agent did not know, grouped and counted. Answer one once and it handles it next time."
      right={<PeriodPicker value={period} onChange={(p) => { setRows(null); setPeriod(p); }} />}
    >
      {failed && <p role="alert" className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink-secondary">Could not load this. Please refresh.</p>}
      {!canEdit && <p className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink-secondary">You can look at this, but only people with Knowledge Base access can answer.</p>}
      {rows === null && !failed && <div className="min-h-[160px] animate-pulse rounded-2xl bg-border-subtle" />}
      {rows?.length === 0 && (
        <p className="card font-body text-sm text-ink-secondary">Nothing here. The AI agent had an answer for every question in this period.</p>
      )}
      <ul className="space-y-3">
        {rows?.map((row) => (
          <li key={row.question} className="card">
            <p className="font-body text-sm font-semibold text-ink">{row.question}</p>
            <p className="mt-1 font-body text-xs text-ink-secondary">
              {timesLabel(row.count)} · last {when(row.last_at)}
              {row.sample_lead_ids.slice(0, 3).map((id, i) => (
                <span key={id}> · <Link className="font-semibold text-primary underline" href={`/dashboard/conversations?lead=${encodeURIComponent(id)}`}>chat {i + 1}</Link></span>
              ))}
            </p>
            {canEdit && open !== row.question && (
              <button type="button" onClick={() => setOpen(row.question)} className="btn-secondary mt-3 min-h-9">Answer this</button>
            )}
            {canEdit && open === row.question && <AnswerForm row={row} onDone={() => { setOpen(null); void load(); }} />}
          </li>
        ))}
      </ul>
    </SetupShell>
  );
}
