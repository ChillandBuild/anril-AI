"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { PeriodPicker } from "@/components/ai-setup/PeriodPicker";
import { NoAccess, SetupShell, useSetupAccess } from "@/components/ai-setup/SetupShell";
import { Pagination, usePagedList } from "@/components/ui/Pagination";
import { aiSetupApi, questionFromSearch, sameQuestion, type CouldntAnswerRow, type Period } from "@/lib/aiSetupApi";

const FIELD =
  "w-full rounded-xl border border-border bg-white px-3 py-2 font-body text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20";

function when(iso: string) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function Stat({ value, label, accent }: { value: number; label: string; accent?: boolean }) {
  return (
    <div>
      <p className={`font-display text-3xl font-bold ${accent ? "text-primary" : "text-ink"}`}>{value}</p>
      <p className="font-body text-xs text-ink-secondary">{label}</p>
    </div>
  );
}

function AnswerPane({
  row, canEdit, onSaved,
}: {
  row: CouldntAnswerRow;
  canEdit: boolean;
  onSaved: (row: CouldntAnswerRow, thenTest: boolean) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function save(thenTest: boolean) {
    if (busy || !text.trim()) return;
    setBusy(thenTest ? "test" : "save");
    setError(null);
    try {
      await aiSetupApi.answer(row.question, text.trim());
      toast.success("Saved. The AI agent will use this next time.");
      onSaved(row, thenTest);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Could not save. Please try again.");
      setBusy(null);
    }
  }

  const firstChat = row.sample_lead_ids[0];

  return (
    <section className="card flex min-w-0 flex-[3_1_480px] flex-col gap-4" aria-label="Answer this question">
      <div>
        <p className="font-body text-xs text-ink-secondary">
          Customers asked this {row.count} {row.count === 1 ? "time" : "times"} · last {when(row.last_at)}
          {firstChat && (
            <>
              {" · "}
              <Link className="font-semibold text-primary underline" href={`/dashboard/conversations?lead=${encodeURIComponent(firstChat)}`}>
                see chats
              </Link>
            </>
          )}
        </p>
        <h2 className="mt-1 font-display text-xl font-bold text-ink">{row.question}</h2>
      </div>
      {canEdit && (
        <>
          <label className="flex flex-col gap-1.5 font-label text-xs font-bold text-ink">
            Your answer
            <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} rows={4}
              className={`${FIELD} resize-y font-normal`} placeholder="Write it the way you would say it to a customer. It is saved to Teach & offers." />
          </label>
          <div>
            <p className="font-label text-xs font-bold uppercase tracking-wide text-ink-secondary">Anril will say</p>
            <p className={`mt-2 max-w-md whitespace-pre-wrap rounded-xl rounded-bl-sm bg-[#e1f5d6] px-3.5 py-2.5 font-body text-sm ${text.trim() ? "text-ink" : "text-ink-secondary"}`}>
              {text.trim() || "Your answer shows here as the customer will see it."}
            </p>
          </div>
          {error && <p role="alert" className="font-body text-xs text-danger">{error}</p>}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void save(false)} disabled={busy !== null || !text.trim()} className="btn-primary min-h-9 disabled:opacity-50">
              {busy === "save" && <Loader2 size={14} className="animate-spin" aria-hidden />} Save answer
            </button>
            <button type="button" onClick={() => void save(true)} disabled={busy !== null || !text.trim()} className="btn-secondary min-h-9 disabled:opacity-50">
              {busy === "test" && <Loader2 size={14} className="animate-spin" aria-hidden />} Save and test
            </button>
          </div>
        </>
      )}
    </section>
  );
}

export default function CouldntAnswerPage() {
  const router = useRouter();
  const { loading: roleLoading, canView, canEdit } = useSetupAccess();
  const [period, setPeriod] = useState<Period>("30d");
  const [rows, setRows] = useState<CouldntAnswerRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [answered, setAnswered] = useState(0);
  const questionPages = usePagedList(rows ?? [], period);

  const load = useCallback(async () => {
    try {
      const res = await aiSetupApi.couldntAnswer(period);
      setRows(res.questions);
      setFailed(false);
      const wanted = questionFromSearch(window.location.search);
      const match = wanted ? res.questions.find((q) => sameQuestion(q.question, wanted)) : undefined;
      setSelected(match ? match.question : null);
    } catch {
      setFailed(true);
    }
  }, [period]);

  useEffect(() => {
    if (canView) void load();
  }, [canView, load]);

  if (roleLoading) return <div className="m-6 min-h-[320px] animate-pulse rounded-2xl bg-border-subtle" />;
  if (!canView) return <NoAccess />;

  const current = rows?.find((r) => r.question === selected) ?? rows?.[0] ?? null;
  const total = rows?.reduce((sum, r) => sum + r.count, 0) ?? 0;
  const top = rows?.reduce((max, r) => Math.max(max, r.count), 1) ?? 1;

  function onSaved(row: CouldntAnswerRow, thenTest: boolean) {
    setAnswered((n) => n + 1);
    if (thenTest) {
      router.push(`/dashboard/brain?section=test&question=${encodeURIComponent(row.question.slice(0, 2000))}`);
      return;
    }
    const all = rows ?? [];
    const at = all.findIndex((r) => r.question === row.question);
    const rest = all.filter((r) => r.question !== row.question);
    setRows(rest);
    setSelected(rest.length ? rest[Math.min(Math.max(at, 0), rest.length - 1)].question : null);
  }

  return (
    <SetupShell toolbar={<PeriodPicker value={period} onChange={(p) => { setRows(null); setSelected(null); setPeriod(p); }} />}>
      {failed && <p role="alert" className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink-secondary">Could not load this. Please refresh.</p>}
      {!canEdit && <p className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink-secondary">You can look at this, but only people with Knowledge Base access can answer.</p>}
      {rows === null && !failed && <div className="min-h-[160px] animate-pulse rounded-2xl bg-border-subtle" />}
      {rows && (
        <section className="card flex flex-wrap items-center justify-between gap-4 !py-2" aria-label="Summary">
          <div className="flex flex-wrap gap-x-8 gap-y-3 py-3">
            <Stat value={total} label="times Anril had no answer" />
            <Stat value={rows.length} label="different questions" />
            <Stat value={answered} label="answered this visit" accent />
          </div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/login/tealy-poster.png" alt="" width={150} height={150} className="h-[150px] w-[150px] shrink-0 object-contain" />
        </section>
      )}
      {rows?.length === 0 && (
        <p className="card font-body text-sm text-ink-secondary">Nothing here. The AI agent had an answer for every question in this period.</p>
      )}
      {rows && rows.length > 0 && current && (
        <div className="flex flex-wrap items-start gap-4">
          <nav className="card flex min-w-0 flex-[2_1_360px] flex-col gap-1 !p-2" aria-label="Questions">
            <p className="px-2.5 py-1.5 font-body text-xs text-ink-secondary">Most asked first</p>
            {questionPages.pageItems.map((row) => {
              const on = row.question === current.question;
              return (
                <button key={row.question} type="button" aria-pressed={on} onClick={() => setSelected(row.question)}
                  className={`flex w-full items-center gap-3 rounded-xl border-l-[3px] px-3.5 py-3 text-left ${on ? "border-primary bg-primary/5" : "border-transparent hover:bg-slate-50"}`}>
                  <span className="min-w-0 flex-1">
                    <span className="block font-body text-sm font-bold text-ink">{row.question}</span>
                    <span className="block font-body text-xs text-ink-secondary">last {when(row.last_at)}</span>
                    <span className="mt-2 block h-1.5 rounded-full bg-[#eef2f6]">
                      <span className="block h-1.5 rounded-full bg-primary" style={{ width: `${Math.max(4, Math.round((row.count * 100) / top))}%` }} />
                    </span>
                  </span>
                  <span className="min-w-7 text-right font-display text-xl font-bold text-ink">{row.count}×</span>
                </button>
              );
            })}
            <Pagination page={questionPages.page} total={questionPages.total} onPageChange={questionPages.setPage} noun="questions" className="px-2.5" />
          </nav>
          <AnswerPane key={current.question} row={current} canEdit={canEdit} onSaved={onSaved} />
        </div>
      )}
    </SetupShell>
  );
}
