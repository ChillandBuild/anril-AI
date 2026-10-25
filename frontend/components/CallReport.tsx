"use client";

import type { ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import type { CallLog, CallReport as ReportData, ReportMoment } from "@/lib/api";
import { CallScorePill } from "@/components/CallAi";
import { TONE_CHIP, TONE_DOT, formatIstWhen, type Tone } from "@/lib/call-wrapup";
import {
  directionLabel, directionTone, formatSeconds, handlingLabel, handlingTone, hasReportContent, hasVerdict,
  moodLabel, moodTone, temperatureLabel, temperatureTone,
} from "@/lib/call-report";

type Seek = ((seconds: number) => void) | undefined;

const CARD = "rounded-xl border border-[#f1f5f9] bg-white px-3 py-2.5";
const HEADING = "font-label text-[9px] uppercase tracking-widest font-extrabold text-primary mb-1.5";
const BODY = "font-body text-[11px] leading-relaxed text-[#1e293b] break-words";
const MUTED = "font-label text-[10px] text-[#475569] break-words";
const CHIP = "shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded-full border font-label text-[9px] font-bold";

function Chip({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`${CHIP} ${TONE_CHIP[tone]}`}>{children}</span>;
}

/** A clickable timestamp that seeks the audio; plain text when there is no recording to seek. */
function Time({ moment, onSeek }: { moment: Pick<ReportMoment, "time" | "start">; onSeek: Seek }) {
  const base = "shrink-0 font-label text-[10px] font-bold tabular-nums";
  if (!onSeek) return <span className={`${base} text-[#475569]`}>{moment.time}</span>;
  return (
    <button
      type="button"
      onClick={() => onSeek(moment.start)}
      aria-label={`Play from ${moment.time}`}
      className={`${base} rounded px-1 -mx-1 text-primary underline decoration-dotted underline-offset-2 hover:bg-primary-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary`}
    >
      {moment.time}
    </button>
  );
}

function Quote({ text }: { text: string }) {
  return text ? <p className={`${BODY} italic`}>&ldquo;{text}&rdquo;</p> : null;
}

function Verdict({ log }: { log: CallLog }) {
  const temp = temperatureLabel(log.ai_call_status);
  const next = log.ai_summary?.next_action?.trim();
  const when = log.next_action_at ? formatIstWhen(new Date(log.next_action_at), new Date()) : null;
  return (
    <div className={CARD}>
      <p className={HEADING}>Verdict</p>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <CallScorePill log={log} />
        {temp && <Chip tone={temperatureTone(log.ai_call_status)}>{temp}</Chip>}
        {next && (
          <p className={BODY}>
            <span className="font-bold text-[#13284A]">Next:</span> {next}
            {when && <span className="text-[#475569]"> ({when})</span>}
          </p>
        )}
      </div>
    </div>
  );
}

function Mood({ items, onSeek }: { items: ReportData["mood"]; onSeek: Seek }) {
  if (!items?.length) return null;
  const sorted = [...items].sort((a, b) => a.start - b.start);
  return (
    <div className={CARD}>
      <p className={HEADING}>Mood</p>
      <ul className="flex flex-wrap gap-1.5">
        {sorted.map((m, i) => {
          const label = `${m.time} ${moodLabel(m.mood)}`;
          const body = (
            <>
              <span className={`h-2 w-2 rounded-full ${TONE_DOT[moodTone(m.mood)]}`} aria-hidden />
              <span className="tabular-nums">{m.time}</span>
              <span>{moodLabel(m.mood)}</span>
            </>
          );
          const cls = `inline-flex items-center gap-1 px-2 py-1 rounded-full border font-label text-[10px] font-bold ${TONE_CHIP[moodTone(m.mood)]}`;
          return (
            <li key={`${m.start}-${i}`}>
              {onSeek ? (
                <button type="button" title={m.quote} aria-label={`Play from ${label}`} onClick={() => onSeek(m.start)} className={`${cls} hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary`}>
                  {body}
                </button>
              ) : (
                <span title={m.quote} className={cls}>{body}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function TurningPoint({ point, onSeek }: { point: ReportData["turning_point"]; onSeek: Seek }) {
  if (!point) return null;
  return (
    <div className={CARD}>
      <p className={HEADING}>Turning point</p>
      <div className="flex flex-wrap items-center gap-2 mb-1">
        <Time moment={point} onSeek={onSeek} />
        <Chip tone={directionTone(point.direction)}>{directionLabel(point.direction)}</Chip>
      </div>
      <Quote text={point.quote} />
      {point.why && <p className={`${MUTED} mt-1`}>{point.why}</p>}
    </div>
  );
}

function Objections({ items, onSeek }: { items: ReportData["objections"]; onSeek: Seek }) {
  if (!items?.length) return null;
  return (
    <div className={CARD}>
      <p className={HEADING}>Objections</p>
      <ul className="flex flex-col gap-2">
        {items.map((o, i) => (
          <li key={`${o.start}-${i}`} className="flex flex-col gap-0.5">
            <div className="flex flex-wrap items-center gap-2">
              <Time moment={o} onSeek={onSeek} />
              <Chip tone={handlingTone(o.handling)}>{handlingLabel(o.handling)}</Chip>
            </div>
            <Quote text={o.quote} />
            {o.why && <p className={MUTED}>{o.why}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Promises({ items, onSeek }: { items: ReportData["promises"]; onSeek: Seek }) {
  if (!items?.length) return null;
  return (
    <div className={CARD}>
      <p className={HEADING}>Promises</p>
      <ul className="flex flex-col gap-2">
        {items.map((p, i) => (
          <li key={`${p.start}-${i}`} className="flex flex-col gap-0.5">
            <div className="flex flex-wrap items-center gap-2">
              <Time moment={p} onSeek={onSeek} />
              {p.risky && (
                <Chip tone="blocked">
                  <AlertTriangle size={9} aria-hidden /> Risky
                </Chip>
              )}
            </div>
            <Quote text={p.quote} />
            {p.risky && p.why && <p className={MUTED}>{p.why}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Coach({ coach, onSeek }: { coach: ReportData["coach"]; onSeek: Seek }) {
  if (!coach) return null;
  return (
    <div className="rounded-xl border border-primary-muted bg-primary-light px-3 py-2.5">
      <p className={HEADING}>Coach</p>
      <div className="flex flex-wrap items-baseline gap-2">
        <Time moment={coach} onSeek={onSeek} />
        <p className={`${BODY} font-bold text-[#13284A]`}>{coach.tip}</p>
      </div>
      {coach.quote && <div className="mt-1"><Quote text={coach.quote} /></div>}
    </div>
  );
}

function Talk({ log }: { log: CallLog }) {
  const talk = log.evaluation?.report?.talk;
  const stats: [string, string][] = [];
  if (log.talk_share != null) stats.push(["Talk share", `${Math.round(log.talk_share)}%`]);
  if (log.interruption_count != null) stats.push(["Interruptions", String(log.interruption_count)]);
  if (talk?.longest_monologue_s != null) stats.push(["Longest monologue", formatSeconds(talk.longest_monologue_s)]);
  if (talk?.dead_air_s != null) stats.push(["Dead air", formatSeconds(talk.dead_air_s)]);
  if (stats.length === 0) return null;
  return (
    <div className={CARD}>
      <p className={HEADING}>Talk</p>
      <dl className="flex flex-wrap gap-x-4 gap-y-1.5">
        {stats.map(([label, value]) => (
          <div key={label}>
            <dt className="font-label text-[9px] uppercase tracking-widest font-bold text-[#94a3b8]">{label}</dt>
            <dd className="font-body text-[11px] font-bold text-[#13284A]">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Manager-only Call Report: verdict, mood, turning point, objections, promises, coach, talk. */
export function CallReport({ log, onSeek }: { log: CallLog; onSeek?: (seconds: number) => void }) {
  const report = log.evaluation?.report;
  // No report (old, early-exit or failed calls) -> nothing, so those calls look exactly as before.
  if (!hasReportContent(report)) return null;
  return (
    <section aria-label="Call report" className="flex flex-col gap-2.5">
      {hasVerdict(log) && <Verdict log={log} />}
      <Mood items={report?.mood} onSeek={onSeek} />
      <TurningPoint point={report?.turning_point} onSeek={onSeek} />
      <Objections items={report?.objections} onSeek={onSeek} />
      <Promises items={report?.promises} onSeek={onSeek} />
      <Coach coach={report?.coach} onSeek={onSeek} />
      <Talk log={log} />
    </section>
  );
}
