"use client";
import { cn } from "@/lib/utils";

const SEGMENT_CONFIG = {
  A: {
    label: "Hot",
    bg: "bg-segment-a-bg",
    text: "text-segment-a-text",
    border: "border-segment-a-border",
  },
  B: {
    label: "Warm",
    bg: "bg-segment-b-bg",
    text: "text-segment-b-text",
    border: "border-segment-b-border",
  },
  C: {
    label: "Cold",
    bg: "bg-segment-c-bg",
    text: "text-segment-c-text",
    border: "border-segment-c-border",
  },
  D: {
    label: "Not interested",
    bg: "bg-segment-d-bg",
    text: "text-segment-d-text",
    border: "border-segment-d-border",
  },
};

export function SegmentBadge({ segment }: { segment: "A" | "B" | "C" | "D" }) {
  const cfg = SEGMENT_CONFIG[segment] ?? SEGMENT_CONFIG.C;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full font-mono text-[10.5px] font-semibold border leading-tight shrink-0 shadow-2xs transition-all",
        cfg.bg,
        cfg.text,
        cfg.border
      )}
    >
      <span>{cfg.label}</span>
    </span>
  );
}
