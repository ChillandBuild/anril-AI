"use client";

import { ChevronRight } from "lucide-react";
import type { Template, UsageEntry } from "../types";
import { STATUS_COLORS, languageName } from "../types";
import { cardNote, statusLabel } from "../template-card-model";

/** Phone layout: one compact row per template, a tiny picture of its look on the left. */
function Thumb({ template: t }: { template: Template }) {
  const cards = t.carousel_cards ?? [];
  const media = (t.header_media_type ?? "").toUpperCase();
  const src = t.header_media_url && /^https?:/.test(t.header_media_url) ? t.header_media_url : undefined;
  return (
    <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-[#efe7dd] p-1.5">
      {cards.length ? (
        <div className="flex h-full w-full gap-1">
          <span className="flex-1 rounded-md" style={{ background: "linear-gradient(180deg,#7a1f3d,#e7a873)" }} />
          <span className="flex-1 rounded-md" style={{ background: "linear-gradient(180deg,#b4531c,#e9a55a)" }} />
        </div>
      ) : media === "IMAGE" && src ? (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img src={src} alt="" loading="lazy" className="h-full w-full rounded-md object-cover" />
      ) : (
        <div className="flex h-full w-full flex-col justify-center gap-1 rounded-md bg-white px-1.5">
          <span className="h-1 w-full rounded bg-[#cbd5e1]" />
          <span className="h-1 w-3/4 rounded bg-[#cbd5e1]" />
          <span className="h-1 w-1/2 rounded bg-[#cbd5e1]" />
        </div>
      )}
    </div>
  );
}

const NOTE_SHORT: Record<string, { text: string; cls: string }> = {
  "staff-marketing": { text: "⚠ Staff alert: change to Utility ›", cls: "text-[#b3361b]" },
  rejected: { text: "Fix and send again ›", cls: "text-[#b42318]" },
  paused: { text: "Paused by Meta · see why ›", cls: "text-[#475569]" },
  disabled: { text: "Turned off by Meta · make a new copy", cls: "text-[#b42318]" },
};

export default function TemplateRow({
  template: t,
  usage,
  onOpen,
}: {
  template: Template;
  usage?: UsageEntry[];
  onOpen: (t: Template) => void;
}) {
  const status = STATUS_COLORS[t.status] ?? STATUS_COLORS.PENDING;
  const note = cardNote(t, usage);
  const short = note ? NOTE_SHORT[note.kind] : undefined;
  return (
    <button
      type="button"
      onClick={() => onOpen(t)}
      className="flex w-full items-center gap-3 rounded-2xl border border-[#e7e2da] bg-white p-3 text-left shadow-sm transition active:scale-[0.99]"
    >
      <Thumb template={t} />
      <div className="min-w-0 flex-1">
        <p className="truncate font-label text-[15px] font-bold text-ink">{t.name}</p>
        <div className="mt-1 flex min-w-0 items-center gap-2">
          <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-[12px] font-semibold ${status.bg} ${status.text}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${status.dot}`} />
            {statusLabel(t.status)}
          </span>
          <span className="truncate text-[12.5px] text-ink-muted">
            {t.category.charAt(0) + t.category.slice(1).toLowerCase()} · {languageName(t.language)}
          </span>
        </div>
        {short && <p className={`mt-1 truncate text-[12.5px] font-medium ${short.cls}`}>{short.text}</p>}
      </div>
      <ChevronRight size={16} className="shrink-0 text-ink-muted" aria-hidden="true" />
    </button>
  );
}
