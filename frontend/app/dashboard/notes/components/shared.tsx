"use client";
import { useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp, Plus, Tag, X } from "lucide-react";
import { formatDateTime } from "@/lib/utils";
import { api, type CallLog } from "@/lib/api";
import { CallAiDetail, MaskedTranscript } from "@/components/CallAi";
import { TONE_CHIP, TONE_DOT, callResultKey, callResultLabel, callResultTone } from "@/lib/call-wrapup";

// ─── Tag system ───────────────────────────────────────────────────────────────
export const PRESET_TAGS = [
  { label: "Follow-up", color: "bg-blue-100 text-blue-700 border-blue-200" },
  { label: "Important", color: "bg-red-100 text-red-700 border-red-200" },
  { label: "Callback", color: "bg-amber-100 text-amber-700 border-amber-200" },
  { label: "Pricing", color: "bg-primary-100 text-primary-700 border-primary-200" },
  { label: "Visit", color: "bg-green-100 text-green-700 border-green-200" },
  { label: "Brochure", color: "bg-teal-100 text-teal-700 border-teal-200" },
  { label: "Not interested", color: "bg-gray-100 text-gray-600 border-gray-200" },
  { label: "Hot lead", color: "bg-orange-100 text-orange-700 border-orange-200" },
];

export function tagStyle(label: string): string {
  const found = PRESET_TAGS.find((t) => t.label.toLowerCase() === label.toLowerCase());
  return found?.color ?? "bg-primary-light text-primary border-primary-muted";
}

// Keep-style pastel card backgrounds, keyed by a note's first tag
const TAG_CARD_BG: Record<string, string> = {
  "Follow-up": "bg-blue-50/70 border-blue-100",
  "Important": "bg-red-50/70 border-red-100",
  "Callback": "bg-amber-50/70 border-amber-100",
  "Pricing": "bg-primary-50/70 border-primary-100",
  "Visit": "bg-green-50/70 border-green-100",
  "Brochure": "bg-teal-50/70 border-teal-100",
  "Not interested": "bg-[#f1f5f9]/70 border-[#e2e8f0]",
  "Hot lead": "bg-orange-50/70 border-orange-100",
};
const DEFAULT_CARD_BG = "bg-white border-[#e2e8f0]";
const PINNED_CARD_BG = "bg-amber-50/60 border-amber-200";

// Notes saved with a Title show "Title\n\nBody" — split them so the title can
// be shown collapsed and the body revealed on click.
export function splitNoteContent(content: string): { title: string | null; body: string } {
  const idx = content.indexOf("\n\n");
  if (idx === -1) return { title: null, body: content };
  const title = content.slice(0, idx);
  const body = content.slice(idx + 2);
  if (!title.trim() || title.includes("\n")) return { title: null, body: content };
  return { title, body };
}

export function cardBgFor(note: { tags?: string[]; is_pinned: boolean }): string {
  if (note.is_pinned) return PINNED_CARD_BG;
  const tag = note.tags?.[0];
  if (tag && TAG_CARD_BG[tag]) return TAG_CARD_BG[tag];
  return DEFAULT_CARD_BG;
}

// Solid dot colors for the timeline rail, keyed by a note's first tag
const TAG_DOT_COLOR: Record<string, string> = {
  "Follow-up": "bg-blue-400",
  "Important": "bg-red-400",
  "Callback": "bg-amber-400",
  "Pricing": "bg-primary-400",
  "Visit": "bg-green-400",
  "Brochure": "bg-teal-400",
  "Not interested": "bg-[#94a3b8]",
  "Hot lead": "bg-orange-400",
};

export function dotColorFor(note: { tags?: string[]; is_pinned: boolean }): string {
  if (note.is_pinned) return "bg-amber-400";
  const tag = note.tags?.[0];
  if (tag && TAG_DOT_COLOR[tag]) return TAG_DOT_COLOR[tag];
  return "bg-primary/70";
}

// ─── Score pill ─────────────────────────────────────────────────────────────────
export function scoreBadgeColor(score: number): string {
  if (score >= 70) return "bg-emerald-50 text-emerald-600";
  if (score >= 40) return "bg-amber-50 text-amber-600";
  return "bg-rose-50 text-rose-600";
}

// ─── Call outcome → dot color ───────────────────────────────────────────────────
export function outcomeDotColor(log: Pick<CallLog, "outcome" | "manual_status">): string {
  const key = callResultKey(log);
  return key ? TONE_DOT[callResultTone(key)] : "bg-primary/70";
}

// ─── Sentiment ──────────────────────────────────────────────────────────────────
const SENTIMENT_CHIP_COLOR: Record<string, string> = {
  positive: "bg-emerald-50 text-emerald-700 border-emerald-200",
  neutral: "bg-[#f1f5f9] text-[#334155] border-[#e2e8f0]",
  negative: "bg-rose-50 text-rose-700 border-rose-200",
};

export function sentimentChipColor(sentiment?: string | null): string {
  return (sentiment && SENTIMENT_CHIP_COLOR[sentiment.toLowerCase()]) || "bg-[var(--primary-50)] text-primary border-[var(--primary-100)]";
}

const SENTIMENT_DOT_COLOR: Record<string, string> = {
  positive: "bg-emerald-400",
  neutral: "bg-[#d6cfc9]",
  negative: "bg-rose-400",
};

export function sentimentDotColor(sentiment?: string | null): string {
  return (sentiment && SENTIMENT_DOT_COLOR[sentiment.toLowerCase()]) || "bg-[#e2e8f0]";
}

// Small dot-row showing sentiment per call, oldest → newest (logs arrive newest-first)
export function SentimentTrend({ logs }: { logs: CallLog[] }) {
  const withSentiment = [...logs].filter((l) => l.ai_summary?.sentiment).reverse();
  if (withSentiment.length < 2) return null;
  return (
    <div className="flex items-center gap-1" title="Sentiment trend (oldest → newest)">
      {withSentiment.map((l) => (
        <span
          key={l.id}
          title={`${formatDateTime(l.created_at)} · ${l.ai_summary?.sentiment}`}
          className={`w-2.5 h-2.5 rounded-full ${sentimentDotColor(l.ai_summary?.sentiment)}`}
        />
      ))}
    </div>
  );
}

// ─── Timeline rail ───────────────────────────────────────────────────────────────
export function TimelineItem({
  color = "bg-primary",
  isLast = false,
  children,
}: {
  color?: string;
  isLast?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="relative pl-6 pb-3 last:pb-0">
      {!isLast && <span className="absolute left-[4.5px] top-3 bottom-0 w-px bg-[#e2e8f0]" />}
      <span className={`absolute left-0 top-2 w-[11px] h-[11px] rounded-full ring-4 ring-white ${color}`} />
      {children}
    </div>
  );
}

// ─── Segment badges ────────────────────────────────────────────────────────────
export const SEGMENT_COLORS: Record<string, string> = {
  A: "bg-rose-100 text-rose-600",
  B: "bg-[var(--primary-50)] text-primary",
  C: "bg-blue-50 text-blue-600",
  D: "bg-[#f1f5f9] text-[#475569]",
};
export const SEGMENT_LABELS: Record<string, string> = {
  A: "Hot", B: "Warm", C: "Cold", D: "Not interested",
};

// ─── Tag chip + selector ────────────────────────────────────────────────────────
export function TagChip({ label, onRemove }: { label: string; onRemove?: () => void }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border font-label text-[10px] font-semibold ${tagStyle(label)}`}>
      {label}
      {onRemove && (
        <button onClick={onRemove} className="hover:opacity-70 transition-opacity">
          <X size={9} />
        </button>
      )}
    </span>
  );
}

export function TagSelector({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (tags: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");

  function toggle(label: string) {
    if (selected.includes(label)) {
      onChange(selected.filter((t) => t !== label));
    } else {
      onChange([...selected, label]);
    }
  }

  function addCustom() {
    const t = custom.trim();
    if (t && !selected.includes(t)) onChange([...selected, t]);
    setCustom("");
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-white border border-[#e2e8f0] font-label text-xs text-[#475569] hover:text-[#13284A] hover:bg-[#f8fafc] transition-colors"
      >
        <Tag size={11} />
        {selected.length > 0 ? `${selected.length} tag${selected.length > 1 ? "s" : ""}` : "Add tags"}
      </button>
      {open && (
        <div className="absolute bottom-full mb-1 left-0 z-30 w-56 bg-white rounded-xl shadow-lg border border-[#e2e8f0] p-3 space-y-2">
          <p className="font-label text-[10px] text-[#94a3b8] uppercase tracking-wider">Select tags</p>
          <div className="flex flex-wrap gap-1.5">
            {PRESET_TAGS.map((t) => (
              <button
                key={t.label}
                onClick={() => toggle(t.label)}
                className={`px-2 py-0.5 rounded-full border font-label text-[10px] font-semibold transition-all ${
                  selected.includes(t.label)
                    ? t.color + " ring-2 ring-offset-1 ring-current"
                    : "bg-[#f8fafc] border-[#e2e8f0] text-[#94a3b8] hover:border-[#d6cfc9]"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="flex gap-1.5">
            <input
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCustom(); } }}
              placeholder="Custom tag…"
              className="flex-1 px-2 py-1 rounded-lg bg-[#f8fafc] border border-[#e2e8f0] font-label text-xs focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <button onClick={addCustom} className="px-2 py-1 rounded-lg bg-primary text-white font-label text-xs hover:bg-primary/90">
              <Plus size={11} />
            </button>
          </div>
          <button onClick={() => setOpen(false)} className="w-full text-center font-label text-[10px] text-[#94a3b8] hover:text-[#1e293b]">Done</button>
        </div>
      )}
    </div>
  );
}

// ─── AI Call Summary card ───────────────────────────────────────────────────────
const SUMMARY_FIELD_LABELS: Record<"course" | "budget" | "timeline", string> = {
  course: "Course",
  budget: "Budget",
  timeline: "Timeline",
};
const PLAYBACK_RATES = [1, 1.25, 1.5, 2];

export function AiSummaryCard({
  log,
  prevSummary,
  onGenerated,
}: {
  log: CallLog;
  prevSummary?: CallLog["ai_summary"];
  onGenerated?: (updated: CallLog) => void;
}) {
  const [open, setOpen] = useState(false);
  const [rate, setRate] = useState(1);
  const audioRef = useRef<HTMLAudioElement>(null);
  const s = log.ai_summary;

  function setPlaybackRate(r: number) {
    setRate(r);
    if (audioRef.current) audioRef.current.playbackRate = r;
  }

  async function refresh() {
    try {
      onGenerated?.(await api.calls.getLog(log.id));
    } catch {
      // the next page load picks the new state up
    }
  }

  if (!s) {
    // Summaries are made automatically after transcription; until then show the
    // processing stage (or Retry when it failed) instead of an on-demand button.
    if (log.provider !== "telecmi" || !log.ai_status) return null;
    return (
      <div className="p-4 bg-white rounded-2xl border border-[#e2e8f0] border-l-4 border-l-[#e2e8f0] shadow-sm hover:shadow-md transition-shadow">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="w-full flex items-center justify-between gap-2 text-left"
        >
          <div className="flex-1 min-w-0">
            <p className="font-label text-xs font-semibold text-[#1e293b]">
              {formatDateTime(log.created_at)}
              {log.duration_seconds != null && ` · ${log.duration_seconds}s`}
            </p>
            {callResultKey(log) && (
              <span className={`inline-block mt-1 px-2 py-0.5 rounded-full border font-label text-[10px] font-bold ${TONE_CHIP[callResultTone(callResultKey(log))]}`}>
                {callResultLabel(callResultKey(log))}
              </span>
            )}
          </div>
          <span className="p-1.5 rounded-lg text-[#94a3b8] shrink-0">
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </span>
        </button>
        {open && (
          <div className="mt-3 space-y-2.5 pt-3 border-t border-[#f1f5f9]">
            {log.recording_url && (
              <audio controls preload="none" src={log.recording_url} className="w-full h-8" />
            )}
            <CallAiDetail log={log} onChanged={() => void refresh()} />
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="p-4 bg-white rounded-2xl border border-[#e2e8f0] border-l-4 border-l-[var(--primary-100)] shadow-sm hover:shadow-md transition-shadow">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <div className="flex-1 min-w-0">
          <p className="font-label text-xs font-semibold text-[#1e293b]">
            {formatDateTime(log.created_at)}
            {log.duration_seconds != null && ` · ${log.duration_seconds}s`}
          </p>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            {callResultKey(log) && (
              <span className={`px-2 py-0.5 rounded-full border font-label text-[10px] font-bold ${TONE_CHIP[callResultTone(callResultKey(log))]}`}>
                {callResultLabel(callResultKey(log))}
              </span>
            )}
            {log.score != null && (
              <span className={`px-2 py-0.5 rounded-full font-label text-[10px] font-bold ${scoreBadgeColor(log.score)}`}>
                Score {log.score}/100
              </span>
            )}
          </div>
          {s.brief && !open && (
            <p className="font-body text-xs text-[#475569] mt-1.5 truncate max-w-xl">
              {s.brief}
            </p>
          )}
        </div>
        <span className="p-1.5 rounded-lg text-[#94a3b8] shrink-0">
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </button>
      {open && (
        <div className="mt-3 space-y-2 pt-3 border-t border-[#f1f5f9]">
          {s.brief && (
            <div className="p-3 bg-[#f8fafc] border border-[#f1f5f9] rounded-xl">
              <p className="font-label text-[10px] font-bold text-primary uppercase tracking-wide mb-1">Call Brief</p>
              <p className="font-body text-xs text-[#1e293b] leading-relaxed font-medium">
                {s.brief}
              </p>
            </div>
          )}
          {(Object.keys(SUMMARY_FIELD_LABELS) as Array<keyof typeof SUMMARY_FIELD_LABELS>).map((k) => {
            let v = s[k];
            if (k === "course" && !v) {
              v = s.product;
            }
            if (!v) return null;
            const prev = prevSummary?.[k];
            const changed = !!prev && prev !== v;
            return (
              <p key={k} className="font-body text-xs text-[#334155]">
                <span className="font-semibold text-[#13284A]">{SUMMARY_FIELD_LABELS[k]}:</span> {v}
                {changed && (
                  <span className="ml-1.5 px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-600 font-label text-[9px] font-bold align-middle">
                    was {prev}
                  </span>
                )}
              </p>
            );
          })}
          {(s.sentiment || s.next_action) && (
            <div className="flex items-center gap-1.5 flex-wrap pt-1">
              {s.sentiment && (
                <span className={`px-2 py-0.5 rounded-full border font-label text-[10px] font-bold uppercase ${sentimentChipColor(s.sentiment)}`}>
                  {s.sentiment}
                </span>
              )}
              {s.next_action && (
                <span className="px-2 py-0.5 rounded-full border bg-primary-light text-primary border-primary-muted font-label text-[10px] font-semibold">
                  Next: {s.next_action}
                </span>
              )}
            </div>
          )}
          {log.recording_url && (
            <div className="mt-2 space-y-1" onClick={(e) => e.stopPropagation()}>
              <audio ref={audioRef} controls src={log.recording_url} className="w-full h-8" />
              <div className="flex items-center gap-1">
                <span className="font-label text-[9px] text-[#94a3b8] uppercase mr-1">Speed</span>
                {PLAYBACK_RATES.map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => setPlaybackRate(r)}
                    className={`px-1.5 py-0.5 rounded font-label text-[9px] font-bold transition-colors ${
                      rate === r ? "bg-primary text-white" : "bg-[#f1f5f9] text-[#475569] hover:bg-[#e2e8f0]"
                    }`}
                  >
                    {r}x
                  </button>
                ))}
              </div>
            </div>
          )}
          <MaskedTranscript preview={log.transcript_preview} callLogId={log.id} />
        </div>
      )}
    </div>
  );
}
