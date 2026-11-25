import { cn } from "@/lib/utils";

/** Initials for a chat: first letters of up to two words of the name, else "#". */
export function chatInitials(name?: string | null): string {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "#";
  const letters = words.slice(0, 2).map((w) => Array.from(w)[0] ?? "");
  return letters.join("").toUpperCase() || "#";
}

const TINT: Record<string, string> = {
  A: "bg-rose-100 text-rose-700",
  B: "bg-amber-100 text-amber-800",
  C: "bg-slate-200 text-slate-700",
};

/** Round initials avatar, tinted by segment (Hot = rose, Warm = amber, Cold = slate). Phone layout only. */
export function PhoneAvatar({ name, segment, size = 46, className }: { name?: string | null; segment?: string | null; size?: number; className?: string }) {
  return (
    <span
      aria-hidden="true"
      style={{ width: size, height: size }}
      className={cn(
        "flex shrink-0 select-none items-center justify-center rounded-full font-display text-[15px] font-bold",
        TINT[segment ?? ""] ?? "bg-slate-100 text-slate-600",
        className
      )}
    >
      {chatInitials(name)}
    </span>
  );
}

const SEGMENT_CHIP: Record<string, { label: string; cls: string }> = {
  A: { label: "Hot", cls: "bg-rose-50 text-rose-700" },
  B: { label: "Warm", cls: "bg-amber-50 text-amber-800" },
  C: { label: "Cold", cls: "bg-slate-100 text-slate-600" },
};

/** Small Hot / Warm / Cold chip; nothing for other segments. */
export function SegmentChip({ segment, className }: { segment?: string | null; className?: string }) {
  const chip = SEGMENT_CHIP[segment ?? ""];
  if (!chip) return null;
  return (
    <span className={cn("inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[10.5px] font-bold leading-4", chip.cls, className)}>
      {chip.label}
    </span>
  );
}
