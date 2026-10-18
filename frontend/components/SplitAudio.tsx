"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { KeyboardEvent, MouseEvent } from "react";
import type { SpeechSegments } from "@/lib/api";
import { hasSegments, segmentsDuration, speechBars } from "@/lib/call-report";

export interface SplitAudioHandle {
  seek(seconds: number): void;
}

interface SplitAudioProps {
  src: string;
  segments?: { telecaller?: SpeechSegments; customer?: SpeechSegments } | null;
  telecallerLabel?: string;
  leadLabel?: string;
}

type Mode = "both" | "telecaller" | "lead";

// The recording is stereo: the telecaller is the right channel (index 1), the lead the left (index 0).
const LEFT = 0;
const RIGHT = 1;

const MODES: { id: Mode; label: (t: string, l: string) => string }[] = [
  { id: "both", label: () => "Both" },
  { id: "telecaller", label: (t) => `${t} only` },
  { id: "lead", label: (_t, l) => `${l} only` },
];

/**
 * Gain for each route (source channel -> output ear). One voice is sent to BOTH ears, so
 * "Telecaller only" is right->left plus right->right, with both left routes muted.
 */
const ROUTE_GAINS: Record<Mode, Record<string, number>> = {
  both: { "0-0": 1, "0-1": 0, "1-0": 0, "1-1": 1 }, // original stereo, untouched
  telecaller: { "0-0": 0, "0-1": 0, "1-0": 1, "1-1": 1 },
  lead: { "0-0": 1, "0-1": 1, "1-0": 0, "1-1": 0 },
};

interface Graph {
  ctx: AudioContext;
  gains: Record<string, GainNode>;
}

/**
 * Splitter -> four route gains -> merger -> speakers:
 *   source -> ChannelSplitter(2) --ch0--> gain 0-0 -> merger in 0 (left ear)
 *                                |        gain 0-1 -> merger in 1 (right ear)
 *                                +-ch1--> gain 1-0 -> merger in 0
 *                                         gain 1-1 -> merger in 1
 * A mode only changes the four gain values, so switching never rebuilds the graph.
 */
function buildGraph(audio: HTMLAudioElement): Graph {
  const ctx = new AudioContext();
  const source = ctx.createMediaElementSource(audio);
  const splitter = ctx.createChannelSplitter(2);
  const merger = ctx.createChannelMerger(2);
  source.connect(splitter);
  const gains: Record<string, GainNode> = {};
  for (const from of [LEFT, RIGHT]) {
    for (const to of [LEFT, RIGHT]) {
      const gain = ctx.createGain();
      splitter.connect(gain, from);
      gain.connect(merger, 0, to);
      gains[`${from}-${to}`] = gain;
    }
  }
  merger.connect(ctx.destination);
  return { ctx, gains };
}

function applyMode(graph: Graph, mode: Mode) {
  for (const [route, value] of Object.entries(ROUTE_GAINS[mode])) graph.gains[route].gain.value = value;
}

const TRACK = "relative block w-full h-3 rounded-full bg-[#f1f5f9] overflow-hidden cursor-pointer";

export const SplitAudio = forwardRef<SplitAudioHandle, SplitAudioProps>(function SplitAudio(
  { src, segments, telecallerLabel = "Telecaller", leadLabel = "Lead" },
  ref,
) {
  const audioRef = useRef<HTMLAudioElement>(null);
  // createMediaElementSource may run only once per <audio>, so the graph lives in a ref.
  const graphRef = useRef<Graph | null>(null);
  const [mode, setMode] = useState<Mode>("both");
  const [splitUnavailable, setSplitUnavailable] = useState(false);
  const [metaDuration, setMetaDuration] = useState<number | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const split = hasSegments(segments) && !splitUnavailable;
  const showBars = hasSegments(segments);

  useImperativeHandle(ref, () => ({
    seek(seconds: number) {
      const audio = audioRef.current;
      if (!audio) return;
      audio.currentTime = seconds;
      audio.play().catch(() => {
        // Autoplay can be blocked; the playhead has still moved, so the user can press play.
      });
    },
  }), []);

  /** Build the graph on first need. Returns null (and hides the toggle) if Web Audio fails. */
  const ensureGraph = useCallback((): Graph | null => {
    if (graphRef.current) return graphRef.current;
    const audio = audioRef.current;
    if (!audio) return null;
    try {
      graphRef.current = buildGraph(audio);
      return graphRef.current;
    } catch {
      // Nothing was attached to the element, so plain playback keeps working.
      setSplitUnavailable(true);
      return null;
    }
  }, []);

  const resume = useCallback((graph: Graph) => {
    if (graph.ctx.state === "suspended") graph.ctx.resume().catch(() => setSplitUnavailable(true));
  }, []);

  function choose(next: Mode) {
    setMode(next);
    const graph = ensureGraph();
    if (!graph) return;
    applyMode(graph, next);
    resume(graph);
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const i = MODES.findIndex((m) => m.id === mode);
    const next = MODES[(i + step + MODES.length) % MODES.length].id;
    choose(next);
    e.currentTarget.querySelector<HTMLButtonElement>(`[data-mode="${next}"]`)?.focus();
  }

  // Close the context on src change or unmount. The <audio> is keyed by src, so a new src always
  // gets a fresh element; closing never strands an element that is still in use.
  useEffect(() => {
    return () => {
      const graph = graphRef.current;
      graphRef.current = null;
      graph?.ctx.close().catch(() => {});
    };
  }, [src]);

  // Without CORS headers a crossOrigin="anonymous" load fails outright. Fall back to a plain load.
  const [corsFailed, setCorsFailed] = useState(false);
  useEffect(() => {
    if (corsFailed) audioRef.current?.load();
  }, [corsFailed]);

  function onError() {
    if (!showBars || corsFailed || graphRef.current) return;
    setCorsFailed(true);
    setSplitUnavailable(true);
  }

  const duration = metaDuration ?? segmentsDuration(segments);

  function seekFromClick(e: MouseEvent<HTMLButtonElement>) {
    const audio = audioRef.current;
    if (!audio || !duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    if (!rect.width) return;
    const ratio = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    audio.currentTime = ratio * duration;
    audio.play().catch(() => {});
  }

  const playheadPct = duration ? Math.min((currentTime / duration) * 100, 100) : 0;

  return (
    <div className="flex flex-col gap-2 min-w-0">
      <audio
        key={src}
        ref={audioRef}
        src={src}
        controls
        crossOrigin={showBars && !corsFailed ? "anonymous" : undefined}
        className="w-full h-9"
        onPlay={() => {
          if (!split) return;
          const graph = ensureGraph();
          if (!graph) return;
          applyMode(graph, mode);
          resume(graph);
        }}
        onLoadedMetadata={(e) => {
          const d = e.currentTarget.duration;
          setMetaDuration(Number.isFinite(d) && d > 0 ? d : null);
        }}
        onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
        onError={onError}
      />
      {split && (
        <div
          role="radiogroup"
          aria-label="Which side to hear"
          onKeyDown={onKeyDown}
          className="flex flex-wrap gap-1"
        >
          {MODES.map((m) => {
            const checked = m.id === mode;
            return (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={checked}
                data-mode={m.id}
                tabIndex={checked ? 0 : -1}
                onClick={() => choose(m.id)}
                className={`px-2.5 py-1 rounded-full border font-label text-[10px] font-bold break-words focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary ${
                  checked
                    ? "bg-primary text-white border-primary"
                    : "bg-primary-light text-primary border-primary-muted hover:brightness-95"
                }`}
              >
                {m.label(telecallerLabel, leadLabel)}
              </button>
            );
          })}
        </div>
      )}
      {showBars && (
        <div className="flex flex-col gap-1.5">
          <SpeechRow label={telecallerLabel} segments={segments?.telecaller} duration={duration} playheadPct={playheadPct} barClass="bg-primary" onSeek={seekFromClick} />
          <SpeechRow label={leadLabel} segments={segments?.customer} duration={duration} playheadPct={playheadPct} barClass="bg-navy-800" onSeek={seekFromClick} />
        </div>
      )}
    </div>
  );
});

function SpeechRow({
  label, segments, duration, playheadPct, barClass, onSeek,
}: {
  label: string;
  segments: SpeechSegments | undefined;
  duration: number;
  playheadPct: number;
  barClass: string;
  onSeek: (e: MouseEvent<HTMLButtonElement>) => void;
}) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="w-16 shrink-0 truncate font-label text-[9px] uppercase tracking-widest font-bold text-[#475569]" title={label}>
        {label}
      </span>
      <button type="button" tabIndex={-1} aria-label={`Seek by ${label} speech`} onClick={onSeek} className={`${TRACK} flex-1 min-w-0`}>
        {speechBars(segments, duration).map((bar, i) => (
          <span
            key={i}
            className={`absolute top-0 h-full ${barClass}`}
            style={{ left: `${bar.leftPct}%`, width: `${Math.max(bar.widthPct, 0.3)}%` }}
          />
        ))}
        <span className="absolute top-0 h-full w-px bg-danger" style={{ left: `${playheadPct}%` }} aria-hidden />
      </button>
    </div>
  );
}
