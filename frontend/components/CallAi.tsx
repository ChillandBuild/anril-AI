"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, Clock, Lightbulb, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api, type CallCheck, type CallLog, type CheckKey, type CheckLevel, type EarlyExitCheck, type TranscriptPreview } from "@/lib/api";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { TEMPERATURE_LABEL } from "@/lib/call-wrapup";

function isProcessing(log: CallLog): boolean {
  return log.ai_status === "pending" || log.ai_status === "transcribing" || log.ai_status === "scoring";
}

export function anyProcessing(logs: CallLog[]): boolean {
  return logs.some(isProcessing);
}

const PILL = "shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded-full border font-label text-[9px] max-md:text-xs font-bold";

/** First and last line only; the middle is never sent to the browser.
 *  With callLogId, a "Show in English" toggle sits above the lines: one request, then kept on the call. */
export function MaskedTranscript({ preview, callLogId }: { preview?: TranscriptPreview | null; callLogId?: string }) {
  const [english, setEnglish] = useState<TranscriptPreview | null>(null);
  const [showEnglish, setShowEnglish] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { role, permissions } = useAuthRole();
  if (!preview) return null;
  const canTranslate = !!callLogId && (role === "owner" || permissions.includes("team.manage"));

  async function toggleEnglish() {
    if (showEnglish) {
      setShowEnglish(false);
      return;
    }
    if (english) {
      setShowEnglish(true);
      return;
    }
    if (!callLogId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.calls.translateTranscript(callLogId);
      setEnglish(res.transcript_preview_en ?? null);
      setShowEnglish(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't translate this call.");
    } finally {
      setLoading(false);
    }
  }

  const shown = showEnglish && english ? english : preview;
  return (
    <div className="rounded-xl border border-[#f1f5f9] bg-[#f8fafc] px-3 py-2.5">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <p className="font-label text-[9px] uppercase tracking-widest font-extrabold text-[#94a3b8]">Transcript</p>
        {canTranslate && (
          <button
            type="button"
            onClick={() => void toggleEnglish()}
            disabled={loading}
            aria-pressed={showEnglish}
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 font-label text-xs font-semibold text-primary hover:bg-primary/10 disabled:opacity-60"
          >
            {loading && <Loader2 size={12} className="animate-spin" />}
            {loading ? "Translating..." : showEnglish ? "Show original" : "Show in English"}
          </button>
        )}
      </div>
      {error && <p className="mb-1.5 font-body text-xs text-red-600">{error}</p>}
      <p className="font-body text-[11px] leading-relaxed text-[#1e293b]">{shown.first}</p>
      {shown.last && (
        <>
          <div className="my-1.5 flex items-center gap-2" aria-label={`${shown.hidden_lines} lines hidden`}>
            <span className="h-2 flex-1 rounded-full bg-[repeating-linear-gradient(90deg,#e2e8f0_0_6px,transparent_6px_10px)]" />
            {shown.hidden_lines > 0 && (
              <span className="font-label text-[9px] font-bold text-[#94a3b8] whitespace-nowrap">
                {shown.hidden_lines} {shown.hidden_lines === 1 ? "line" : "lines"} hidden
              </span>
            )}
            <span className="h-2 flex-1 rounded-full bg-[repeating-linear-gradient(90deg,#e2e8f0_0_6px,transparent_6px_10px)]" />
          </div>
          <p className="font-body text-[11px] leading-relaxed text-[#1e293b]">{shown.last}</p>
        </>
      )}
    </div>
  );
}

function ProcessingBanner({ log, onRetried }: { log: CallLog; onRetried?: () => void }) {
  const [retrying, setRetrying] = useState(false);
  if (isProcessing(log)) {
    const scoring = log.ai_status === "scoring";
    return (
      <div className="flex items-center gap-2.5 rounded-xl border border-[#e2e8f0] bg-[#f8fafc] px-3 py-2.5">
        <Loader2 size={14} className="animate-spin text-primary shrink-0" />
        <div>
          <p className="font-body text-[11px] font-bold text-[#13284A]">{scoring ? "Scoring the call…" : "Transcribing the recording…"}</p>
          <p className="font-label text-[10px] text-[#94a3b8]">
            {scoring ? "The score and summary appear here in a moment." : "Long calls take a minute or two. The score and summary follow."}
          </p>
        </div>
      </div>
    );
  }
  if (log.ai_status !== "failed") return null;

  async function retry() {
    setRetrying(true);
    try {
      await api.calls.retryAi(log.id);
      toast.success("Processing restarted");
      onRetried?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not restart processing");
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5">
      <div className="flex items-start gap-2 min-w-0">
        <AlertTriangle size={14} className="text-rose-600 shrink-0 mt-0.5" />
        <div className="min-w-0">
          <p className="font-body text-[11px] font-bold text-rose-800">Processing failed</p>
          <p className="font-label text-[10px] text-rose-700/80 truncate" title={log.ai_error ?? ""}>
            This call wasn&apos;t transcribed or scored after 2 attempts.
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={() => void retry()}
        disabled={retrying}
        className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-white border border-rose-200 px-2.5 py-1.5 max-md:min-h-8 font-label text-[10px] max-md:text-xs font-extrabold text-rose-700 hover:bg-rose-100 disabled:opacity-60 transition-colors"
      >
        <RefreshCw size={11} className={retrying ? "animate-spin" : ""} /> Retry
      </button>
    </div>
  );
}

export const CHECK_LABEL: Record<CheckKey, string> = {
  opening: "Opening", courtesy: "Courtesy & empathy", questions: "Asking questions",
  listening: "Listening", product_info: "Correct product information", doubts: "Clearing doubts",
  clarity: "Clarity", next_step: "Next step", decision: "Asking for the decision", crm_update: "CRM update",
};
const STAGES: { name: string; keys: CheckKey[] }[] = [
  { name: "Connect", keys: ["opening", "courtesy"] },
  { name: "Understand", keys: ["questions", "listening"] },
  { name: "Explain", keys: ["product_info", "doubts", "clarity"] },
  { name: "Close", keys: ["next_step", "decision", "crm_update"] },
];
const LEVEL_LABEL: Record<CheckLevel, string> = {
  excellent: "Excellent", good: "Good", partial: "Partial", poor: "Poor", missing: "Missing",
};
const LEVEL_TONE: Record<CheckLevel, string> = {
  excellent: "text-emerald-700 bg-emerald-50 border-emerald-200",
  good: "text-cyan-700 bg-cyan-50 border-cyan-200",
  partial: "text-amber-700 bg-amber-50 border-amber-200",
  poor: "text-orange-700 bg-orange-50 border-orange-200",
  missing: "text-rose-700 bg-rose-50 border-rose-200",
};
const CAP_NOTE: Record<string, string> = {
  talk_share: "capped by talk share",
  interruptions: "capped by interruptions",
  talk_share_and_interruptions: "capped by talk share and interruptions",
  wrong_info: "wrong information given",
  rude: "rude on the call",
};
const EXPECTED_CRM_LABEL: Record<EarlyExitCheck["expected_crm"], string> = {
  wrong_number: "Wrong number", not_enquired: "Not enquired", callback: "Callback with a date and time",
  language_barrier: "Language barrier", voicemail: "Voicemail / IVR", other: "—",
};

export function scoreColor(score: number): string {
  if (score >= 80) return "text-emerald-700 bg-emerald-50 border-emerald-200";
  if (score >= 60) return "text-cyan-700 bg-cyan-50 border-cyan-200";
  if (score >= 40) return "text-amber-700 bg-amber-50 border-amber-200";
  return "text-rose-700 bg-rose-50 border-rose-200";
}

const MUTED_PILL = `${PILL} bg-[#f8fafc] text-[#94a3b8] border-[#e2e8f0]`;

/** Compact status for a call row. */
export function CallScorePill({ log }: { log: CallLog }) {
  if (log.provider !== "telecmi") return null;
  if (isProcessing(log)) {
    return (
      <span className={`${PILL} bg-[#f8fafc] text-[#475569] border-[#e2e8f0]`}>
        <Loader2 size={9} className="animate-spin" />
        {log.ai_status === "scoring" ? "Marking…" : "Transcribing…"}
      </span>
    );
  }
  switch (log.score_status) {
    case "scored":
    case "provisional":
      return log.score != null ? (
        <span className={`${PILL} ${scoreColor(log.score)}`} title={log.score_status === "provisional" ? "Provisional until the wrap-up is saved" : undefined}>
          {log.score.toFixed(1)}/100{log.score_status === "provisional" ? " · provisional" : ""}
        </span>
      ) : null;
    case "early_exit":
      return <span className={MUTED_PILL}>Early exit</span>;
    case "very_short":
      return <span className={MUTED_PILL}>Not scored · under 30s</span>;
    case "not_connected":
      return <span className={MUTED_PILL}>Not scored · not connected</span>;
    case "failed":
      return <span className={`${PILL} bg-rose-50 text-rose-700 border-rose-200`}>Processing failed</span>;
    default:
      return null;
  }
}

function Quote({ time, text }: { time: string | null; text: string | null }) {
  if (!text) return null;
  return (
    <p className="font-body text-[11px] leading-relaxed text-[#1e293b]">
      {time && <span className="font-label text-[10px] font-bold text-[#94a3b8] mr-1.5">[{time}]</span>}
      &ldquo;{text}&rdquo;
    </p>
  );
}

function CheckRow({ check }: { check: CallCheck }) {
  const [open, setOpen] = useState(false);
  const pending = check.level === null;
  return (
    <div className="rounded-lg">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={pending}
        aria-expanded={open}
        className="grid w-full grid-cols-[minmax(0,1fr)_auto_3.5rem] items-center gap-2 px-2 py-1.5 text-left rounded-lg hover:bg-[#f8fafc] disabled:hover:bg-transparent"
      >
        <span className="font-label text-[11px] font-semibold text-[#334155] truncate">
          {CHECK_LABEL[check.key]}
          {check.proof_missing && <span className="ml-1.5 text-[9px] font-bold text-amber-700">· needs review</span>}
        </span>
        {pending ? (
          <span className={MUTED_PILL}>Waiting for wrap-up</span>
        ) : (
          <span className={`${PILL} ${LEVEL_TONE[check.level as CheckLevel]}`}>{LEVEL_LABEL[check.level as CheckLevel]}</span>
        )}
        <span className="font-label text-[11px] font-bold text-[#13284A] text-right tabular-nums">
          {pending ? "—" : (check.marks ?? 0).toFixed(1)}<span className="text-[#94a3b8] font-semibold"> /{check.full}</span>
        </span>
      </button>
      {open && !pending && (
        <div className="ml-2 border-l-2 border-[#f1f5f9] pl-3 pb-2 space-y-1">
          {check.reason && <p className="font-body text-[11px] text-[#334155]">{check.reason}</p>}
          {check.capped_by && (
            <p className="font-label text-[10px] text-amber-700">
              AI said {check.ai_level ? LEVEL_LABEL[check.ai_level] : "—"}; {CAP_NOTE[check.capped_by]}.
            </p>
          )}
          <Quote time={check.time} text={check.quote} />
        </div>
      )}
    </div>
  );
}

function NumbersLine({ log }: { log: CallLog }) {
  const share = log.talk_share;
  const ipm = log.interruptions_per_5min;
  if (share == null && ipm == null) return null;
  return (
    <p className="font-body text-[11px] text-[#334155]">
      {share != null && (
        <span className={share > 65 ? "text-amber-700 font-bold" : ""}>Talk share {Math.round(share)}%</span>
      )}
      {share != null && ipm != null && <span className="text-[#94a3b8]"> · </span>}
      {ipm != null && (
        <span className={ipm > 1 ? "text-amber-700 font-bold" : ""}>
          Interruptions {ipm.toFixed(1)} per 5 min{log.interruption_count != null ? ` (${log.interruption_count})` : ""}
        </span>
      )}
    </p>
  );
}

function RealConversationCard({ log }: { log: CallLog }) {
  const { role, permissions } = useAuthRole();
  const evaluation = log.evaluation;
  const checks = evaluation?.checks ?? [];
  if (log.score == null || !checks.length) return null;
  const byKey = Object.fromEntries(checks.map((c) => [c.key, c])) as Record<CheckKey, CallCheck>;
  const provisional = log.score_status === "provisional";
  return (
    <div className="rounded-xl border border-[#e2e8f0] bg-white px-3 py-3 space-y-3">
      <div className="flex items-center gap-3">
        <div className={`flex h-14 w-14 shrink-0 flex-col items-center justify-center rounded-xl border ${scoreColor(log.score)}`}>
          <span className="font-display text-lg font-extrabold leading-none tabular-nums">{log.score.toFixed(1)}</span>
          <span className="font-label text-[8px] font-bold opacity-70">/ 100</span>
        </div>
        <div className="min-w-0 space-y-0.5">
          <p className="font-body text-xs font-bold text-[#13284A]">
            Real conversation{provisional && <span className="ml-1.5 font-label text-[10px] font-bold text-amber-700">· provisional until the wrap-up is saved</span>}
          </p>
          <NumbersLine log={log} />
        </div>
      </div>

      {evaluation?.crm_correction && (role === "owner" || permissions.includes("team.manage")) && (
        <p className="flex items-center gap-1.5 rounded-lg border border-primary-100 bg-primary-50 px-2.5 py-1.5 font-label text-[11px] font-bold text-primary-800">
          <Sparkles size={12} className="shrink-0" />
          AI changed {TEMPERATURE_LABEL[evaluation.crm_correction.from]} → {TEMPERATURE_LABEL[evaluation.crm_correction.to]}
          <span className="font-semibold text-primary-700/70">· from the recording</span>
        </p>
      )}

      {(evaluation?.tips?.length ?? 0) > 0 && (
        <div className="space-y-1">
          {evaluation!.tips!.map((tip) => (
            <p key={tip} className="flex items-start gap-1.5 font-body text-[11px] text-amber-800">
              <Lightbulb size={12} className="shrink-0 mt-0.5" /> {tip}
            </p>
          ))}
        </div>
      )}

      {(evaluation?.top_improve?.length ?? 0) > 0 && (
        <div className="rounded-lg bg-[#f8fafc] px-2.5 py-2">
          <p className="font-label text-[9px] uppercase tracking-wider font-extrabold text-[#94a3b8] mb-0.5">Top things to improve</p>
          <p className="font-body text-[11px] font-semibold text-[#13284A]">
            {evaluation!.top_improve!.map((k) => `${CHECK_LABEL[k]} ${(byKey[k]?.marks ?? 0).toFixed(1)}/${byKey[k]?.full}`).join(" · ")}
          </p>
        </div>
      )}

      <div className="space-y-2">
        {STAGES.map((stage) => (
          <div key={stage.name}>
            <p className="font-label text-[9px] uppercase tracking-widest font-extrabold text-[#94a3b8] px-2 mb-0.5">{stage.name}</p>
            {stage.keys.map((k) => byKey[k] && <CheckRow key={k} check={byKey[k]} />)}
          </div>
        ))}
      </div>

      {(evaluation?.unverified_claims?.length ?? 0) > 0 && (
        <div className="border-t border-[#f1f5f9] pt-2">
          <p className="font-label text-[9px] uppercase tracking-wider font-extrabold text-[#94a3b8] mb-1">Not in the knowledge base (not marked down)</p>
          {evaluation!.unverified_claims!.map((c) => (
            <p key={c} className="font-body text-[11px] text-[#334155]">&ldquo;{c}&rdquo;</p>
          ))}
        </div>
      )}
    </div>
  );
}

function EarlyExitCard({ log }: { log: CallLog }) {
  const check = log.evaluation?.early_exit_check;
  if (!check) return null;
  const row = (ok: boolean | null, label: string, note?: string) => (
    <p className="flex items-start gap-1.5 font-body text-[11px] text-[#334155]">
      {ok === null ? <Clock size={12} className="text-[#94a3b8] shrink-0 mt-0.5" /> : ok ? (
        <CheckCircle2 size={12} className="text-emerald-600 shrink-0 mt-0.5" />
      ) : (
        <AlertTriangle size={12} className="text-rose-600 shrink-0 mt-0.5" />
      )}
      <span>{label}{note && <span className="text-[#94a3b8]"> · {note}</span>}</span>
    </p>
  );
  return (
    <div className="rounded-xl border border-[#e2e8f0] bg-white px-3 py-3 space-y-2">
      <div>
        <p className="font-body text-xs font-bold text-[#13284A]">Early exit · not scored</p>
        <p className="font-label text-[10px] text-[#94a3b8]">No real sales discussion happened, so this call doesn&apos;t count in quality or effort.</p>
      </div>
      {row(check.polite, check.polite ? "Stayed polite" : "Not polite on this call")}
      {!check.polite && <Quote time={null} text={check.rude_quote} />}
      {row(check.enquiry_confirmed_early, check.enquiry_confirmed_early ? "Confirmed the enquiry early" : "Didn't confirm the enquiry in the first 30 seconds", "coaching only")}
      {row(
        check.crm_matches,
        check.crm_matches === null
          ? "Wrap-up check pending"
          : check.crm_matches
          ? "Wrap-up matches the call"
          : check.no_wrapup
          ? "No wrap-up saved"
          : "Wrap-up doesn't match the call",
        check.expected_crm !== "other" ? `expected: ${EXPECTED_CRM_LABEL[check.expected_crm]}` : undefined,
      )}
    </div>
  );
}

/** Everything the AI produced for a recorded call, in the order people read it. */
export function CallAiDetail({ log, onChanged }: { log: CallLog; onChanged?: () => void }) {
  if (log.provider !== "telecmi") return null;
  const brief = log.ai_summary?.brief;
  const v4 = log.evaluation?.evaluation_version === 4;
  return (
    <div className="space-y-2.5">
      <ProcessingBanner log={log} onRetried={onChanged} />
      {log.score_status === "very_short" && (
        <p className="font-label text-[10px] text-[#94a3b8]">Not scored · under 30 seconds of talk time. Counted as a dial only.</p>
      )}
      {log.score_status === "not_connected" && (
        <p className="font-label text-[10px] text-[#94a3b8]">Not scored · the customer didn&apos;t answer. Counted as a dial only.</p>
      )}
      {v4 && log.call_group === "real_conversation" && <RealConversationCard log={log} />}
      {v4 && log.call_group === "early_exit" && <EarlyExitCard log={log} />}
      {brief && (
        <div className="rounded-xl border border-[#f1f5f9] bg-white px-3 py-2.5">
          <p className="font-label text-[9px] uppercase tracking-widest font-extrabold text-primary mb-1 flex items-center gap-1">
            <Sparkles size={10} /> Summary
          </p>
          <p className="font-body text-[11px] leading-relaxed text-[#1e293b]">{brief}</p>
        </div>
      )}
      <MaskedTranscript preview={log.transcript_preview} callLogId={log.id} />
    </div>
  );
}
