"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowUpRight,
  Copy,
  CornerUpLeft,
  Eye,
  FileText,
  Image as ImageIcon,
  MoreHorizontal,
  Pencil,
  Phone,
  Play,
  RefreshCw,
  Send,
  Shuffle,
  Trash2,
} from "lucide-react";
import type { Button, Template, UsageEntry } from "../types";
import { CATEGORY_COLORS, STATUS_COLORS, languageName } from "../types";
import { cardNote, statusLabel, usedIn } from "../template-card-model";
import AiraId from "./aira-id";

type TemplateCardProps = {
  template: Template;
  onPreview: (t: Template) => void;
  onEdit?: (t: Template) => void;
  onDelete?: (t: Template) => void;
  onDuplicate?: (t: Template) => void;
  /** "Change to Utility ›": makes a Utility copy of a staff alert filed as Marketing. */
  onMakeUtility?: (t: Template) => void;
  onSend?: (t: Template) => void;
  onSync?: (t: Template) => void;
  onVariations?: (t: Template) => void;
  syncing?: boolean;
  /** Where it is used (the "Used in" line); undefined until the usage call answers. */
  usage?: UsageEntry[];
  usageReady?: boolean;
  /** Shows "Fix and send again" on a rejected template. */
  canFix?: boolean;
};

/* ── the WhatsApp-look preview ───────────────────────────────── */

const WA_WALL = "#EFE7DD";

/** Body text with {{n}} shown as a soft chip, as on the builder. */
function BodyText({ text }: { text: string }) {
  const parts = text.split(/(\{\{\d+\}\})/g);
  return (
    <>
      {parts.map((p, i) =>
        /^\{\{\d+\}\}$/.test(p) ? (
          <span key={i} className="font-semibold text-[#0b7a75]">{p}</span>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

function mediaType(t: Template): "IMAGE" | "VIDEO" | "DOCUMENT" | null {
  const m = (t.header_media_type ?? "").toUpperCase();
  return m === "IMAGE" || m === "VIDEO" || m === "DOCUMENT" ? m : null;
}

function httpUrl(u?: string): string | undefined {
  return u && /^https?:/.test(u) ? u : undefined;
}

// A Meta upload handle ("4::...") isn't a URL and Meta's example links expire,
// so anything that can't load falls back to a labelled placeholder.
function MediaHeader({ template: t }: { template: Template }) {
  const [failed, setFailed] = useState(false);
  const type = mediaType(t);
  if (!type) return null;
  const src = httpUrl(t.header_media_url);
  if (type === "IMAGE" && src && !failed) {
    return (
      /* eslint-disable-next-line @next/next/no-img-element */
      <img
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
        className="block h-[68px] w-full rounded-md object-cover"
      />
    );
  }
  const Icon = type === "VIDEO" ? Play : type === "DOCUMENT" ? FileText : ImageIcon;
  const label = type === "VIDEO" ? "Video" : type === "DOCUMENT" ? "Document" : "Image";
  return (
    <div
      className={`flex h-[52px] w-full items-center justify-center gap-1.5 rounded-md ${
        type === "VIDEO" ? "bg-[#1f2c34] text-white/80" : "bg-[#e9edef] text-[#54656f]"
      }`}
    >
      <Icon size={15} aria-hidden="true" />
      <span className="text-[11px] font-medium">{label}</span>
    </div>
  );
}

function ButtonIcon({ type }: { type: Button["type"] | string }) {
  if (type === "URL") return <ArrowUpRight size={12} aria-hidden="true" />;
  if (type === "COPY_CODE") return <Copy size={11} aria-hidden="true" />;
  if (type === "PHONE_NUMBER" || type === "WHATSAPP_CALL") return <Phone size={11} aria-hidden="true" />;
  if (type === "QUICK_REPLY") return <CornerUpLeft size={11} aria-hidden="true" />;
  return null;
}

function buttonText(b: Button): string {
  if (b.type === "COPY_CODE") return b.text || "Copy code";
  if (b.type === "ONE_TAP") return b.autofill_text || b.text || "Autofill";
  return b.text;
}

function Ticks() {
  return (
    <span className="flex items-center justify-end gap-1 text-[10px] leading-none text-[#8696A0]">
      12:00 PM <span className="text-[#53bdeb]">✓✓</span>
    </span>
  );
}

function Preview({ template: t }: { template: Template }) {
  const cards = t.carousel_cards ?? [];
  if (cards.length) {
    return (
      <div className="space-y-2">
        <div className="w-fit max-w-[92%] rounded-lg rounded-tl-[3px] bg-white px-2.5 py-1.5 shadow-[0_1px_0.5px_rgba(11,20,26,.13)]">
          <p className="line-clamp-1 text-[12.5px] text-[#111B21]"><BodyText text={t.body_text} /></p>
          <Ticks />
        </div>
        <div className="flex gap-2">
          {cards.map((c, i) => {
            const src = httpUrl(c.header_media_url);
            return (
              <div key={i} className="w-[150px] shrink-0 overflow-hidden rounded-lg bg-white p-1 shadow-[0_1px_0.5px_rgba(11,20,26,.13)]">
                {src ? (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img src={src} alt="" loading="lazy" className="h-[52px] w-full rounded-md object-cover" />
                ) : (
                  <div
                    className="h-[52px] w-full rounded-md"
                    style={{ background: i % 2 ? "linear-gradient(135deg,#b4531c,#e9a55a)" : "linear-gradient(135deg,#7a1f3d,#e7a873)" }}
                  />
                )}
                <p className="mt-1 truncate px-1 text-[11.5px] text-[#111B21]">{c.body_text}</p>
                {c.buttons?.[0] && (
                  <p className="flex items-center justify-center gap-1 truncate text-[11.5px] font-medium text-[#027eb5]">
                    {c.buttons[0].text} <ButtonIcon type={c.buttons[0].type} />
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  const hasMedia = !!mediaType(t);
  const headerText = !hasMedia && t.header_text ? t.header_text : "";
  const buttons = t.buttons ?? [];
  return (
    <div className="space-y-1">
      <div className="rounded-lg rounded-tl-[3px] bg-white p-1 shadow-[0_1px_0.5px_rgba(11,20,26,.13)]">
        {hasMedia && <MediaHeader template={t} />}
        <div className="px-1.5 pb-0.5 pt-1">
          {headerText && <p className="mb-0.5 truncate text-[12.5px] font-semibold text-[#111B21]">{headerText}</p>}
          <p
            className={`whitespace-pre-wrap break-words text-[12.5px] leading-[1.45] text-[#111B21] ${
              hasMedia ? "line-clamp-2" : headerText ? "line-clamp-3" : "line-clamp-4"
            }`}
          >
            <BodyText text={t.body_text} />
          </p>
          <Ticks />
        </div>
      </div>
      {buttons.slice(0, 2).map((b, i) => (
        <div
          key={i}
          className="flex h-[30px] items-center justify-center gap-1 rounded-lg bg-white text-[12.5px] font-medium text-[#027eb5] shadow-[0_1px_0.5px_rgba(11,20,26,.13)]"
        >
          <span className="truncate">{buttonText(b)}</span>
          <ButtonIcon type={b.type} />
        </div>
      ))}
    </div>
  );
}

/* ── the coloured note row ───────────────────────────────────── */

function NoteRow({
  template: t,
  usage,
  canFix,
  onPreview,
  onMakeUtility,
}: {
  template: Template;
  usage?: UsageEntry[];
  canFix: boolean;
  onPreview: (t: Template) => void;
  onMakeUtility?: (t: Template) => void;
}) {
  const note = cardNote(t, usage);
  if (!note) return null;
  const linkCls = "font-semibold text-primary hover:underline underline-offset-2";
  const stop = (e: React.MouseEvent) => e.stopPropagation();

  if (note.kind === "staff-marketing") {
    return (
      <p className="line-clamp-2 rounded-lg bg-[#fff4ec] px-2.5 py-1.5 text-[12px] leading-snug text-[#b3361b]">
        <AlertTriangle size={12} className="-mt-0.5 mr-1 inline" aria-hidden="true" />
        Staff alert set as Marketing: costs more, Meta may block.{" "}
        {onMakeUtility && (
          <button type="button" onClick={(e) => { stop(e); onMakeUtility(t); }} className={linkCls}>
            Change to Utility ›
          </button>
        )}
      </p>
    );
  }
  if (note.kind === "pending") {
    return <p className="line-clamp-2 rounded-lg bg-[#fff8e6] px-2.5 py-1.5 text-[12px] leading-snug text-[#a16207]">{note.text}</p>;
  }
  if (note.kind === "paused") {
    return (
      <p className="line-clamp-2 rounded-lg bg-[#f1f5f9] px-2.5 py-1.5 text-[12px] leading-snug text-[#334155]">
        {note.text}{" "}
        <button type="button" onClick={(e) => { stop(e); onPreview(t); }} className={linkCls}>
          See why ›
        </button>
      </p>
    );
  }
  return (
    <p className="line-clamp-2 rounded-lg bg-[#fdeeee] px-2.5 py-1.5 text-[12px] leading-snug text-[#b42318]">
      {note.text}{" "}
      {note.kind === "rejected" && canFix && (
        <Link href={`/dashboard/templates/${t.id}`} onClick={stop} className={linkCls}>
          Fix and send again ›
        </Link>
      )}
    </p>
  );
}

/* ── the ⋯ menu ──────────────────────────────────────────────── */

type MenuItem = { label: string; icon: React.ElementType; onClick: () => void; danger?: boolean };

// The preview clips its overflow, so the menu opens in a portal, pinned under the ⋯ button.
function MoreMenu({ items }: { items: MenuItem[] }) {
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const open = pos !== null;
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      const t = e.target as Node;
      if (!menu.current?.contains(t) && !btn.current?.contains(t)) setPos(null);
    };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setPos(null); };
    const gone = () => setPos(null);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    window.addEventListener("scroll", gone, true);
    window.addEventListener("resize", gone);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("scroll", gone, true);
      window.removeEventListener("resize", gone);
    };
  }, [open]);
  if (!items.length) return null;
  const toggle = () => {
    if (open) return setPos(null);
    const r = btn.current?.getBoundingClientRect();
    if (r) setPos({ top: r.bottom + 6, right: Math.max(8, window.innerWidth - r.right) });
  };
  return (
    <div onClick={(e) => e.stopPropagation()}>
      <button
        ref={btn}
        type="button"
        aria-label="More actions"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
        className="flex h-7 w-8 items-center justify-center rounded-full bg-white text-ink shadow-sm ring-1 ring-black/5 transition hover:bg-[#f8fafc]"
      >
        <MoreHorizontal size={15} />
      </button>
      {pos && createPortal(
        <div
          ref={menu}
          role="menu"
          onClick={(e) => e.stopPropagation()}
          style={{ top: pos.top, right: pos.right }}
          className="fixed z-dialog w-52 overflow-hidden rounded-xl border border-[#e2e8f0] bg-white py-1 shadow-xl"
        >
          {items.map((it) => (
            <button
              key={it.label}
              role="menuitem"
              type="button"
              onClick={() => { setPos(null); it.onClick(); }}
              className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] font-medium transition-colors ${
                it.danger ? "text-red-600 hover:bg-red-50" : "text-ink hover:bg-[#f8fafc]"
              }`}
            >
              <it.icon size={14} aria-hidden="true" />
              {it.label}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </div>
  );
}

function Pill({ icon: Icon, label, onClick }: { icon: React.ElementType; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      className="flex h-7 items-center gap-1 rounded-full bg-white px-2.5 text-[12px] font-semibold text-ink shadow-sm ring-1 ring-black/5 transition hover:bg-[#f8fafc]"
    >
      <Icon size={12} aria-hidden="true" />
      {label}
    </button>
  );
}

/* ── the card ────────────────────────────────────────────────── */

export default function TemplateCard({
  template: t,
  onPreview,
  onEdit,
  onDelete,
  onDuplicate,
  onMakeUtility,
  onSend,
  onSync,
  onVariations,
  syncing = false,
  usage,
  usageReady = false,
  canFix = false,
}: TemplateCardProps) {
  const status = STATUS_COLORS[t.status] ?? STATUS_COLORS.PENDING;
  const cat = CATEGORY_COLORS[t.category] ?? { bg: "bg-gray-50", text: "text-gray-600" };
  const used = usedIn(usage);

  const menu: MenuItem[] = [];
  if (onSend && t.status === "APPROVED") menu.push({ label: "Send to customers", icon: Send, onClick: () => onSend(t) });
  if (onSync) menu.push({ label: syncing ? "Checking with Meta…" : "Check status with Meta", icon: RefreshCw, onClick: () => onSync(t) });
  if (onVariations) menu.push({ label: "Message variations", icon: Shuffle, onClick: () => onVariations(t) });
  if (onDelete) menu.push({ label: "Delete", icon: Trash2, onClick: () => onDelete(t), danger: true });

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onPreview(t)}
      onKeyDown={(e) => { if (e.key === "Enter" && e.target === e.currentTarget) onPreview(t); }}
      aria-label={`${t.name}, ${statusLabel(t.status)}`}
      className="group relative flex h-[328px] cursor-pointer flex-col rounded-2xl border border-[#e7e2da] bg-white shadow-sm outline-none transition-all duration-200 hover:-translate-y-0.5 hover:border-primary-300 hover:shadow-md focus-visible:ring-2 focus-visible:ring-primary-300"
    >
      {/* Preview: fixed height, faded at the bottom, so every card lines up */}
      <div className="relative h-[164px] shrink-0 overflow-hidden rounded-t-2xl px-3 pt-3" style={{ background: WA_WALL }}>
        <Preview template={t} />
        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 h-10"
          style={{ background: `linear-gradient(to bottom, rgba(239,231,221,0), ${WA_WALL})` }}
        />
        {/* Actions: on hover or keyboard focus */}
        <div className="absolute inset-x-0 bottom-0 flex items-center justify-center gap-1.5 bg-gradient-to-t from-black/45 via-black/20 to-transparent px-2 pb-2.5 pt-8 opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100">
          <Pill icon={Eye} label="Preview" onClick={() => onPreview(t)} />
          {onEdit && <Pill icon={Pencil} label="Edit" onClick={() => onEdit(t)} />}
          {onDuplicate && <Pill icon={Copy} label="Copy" onClick={() => onDuplicate(t)} />}
          {onSend && t.status === "APPROVED" && <Pill icon={Send} label="Send" onClick={() => onSend(t)} />}
          <MoreMenu items={menu} />
        </div>
      </div>

      {/* Footer: fixed height */}
      <div className="flex min-h-0 flex-1 flex-col gap-2 px-3.5 pb-3 pt-3">
        <div className="flex items-center justify-between gap-2">
          <p className="min-w-0 truncate font-label text-[15px] font-bold text-ink" title={t.name}>{t.name}</p>
          <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-semibold ${status.bg} ${status.text}`}>
            <span className={`h-2 w-2 rounded-full ${status.dot}`} />
            {statusLabel(t.status)}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide ${cat.bg} ${cat.text}`}>{t.category}</span>
          <span className="rounded-full bg-[#f4f1ec] px-2.5 py-0.5 text-[12px] font-medium text-[#475569]">{languageName(t.language)}</span>
          <AiraId code={t.short_code} className="ml-auto" />
        </div>
        <p className="truncate text-[13px] text-ink-secondary">
          {!usageReady ? (
            <span className="inline-block h-3 w-32 animate-pulse rounded bg-[#f1f5f9] align-middle" />
          ) : (
            <>
              Used in:{" "}
              <span className="font-semibold text-ink">
                {used.kind === "live" && <>{used.icon} {used.label}{used.more > 0 && ` +${used.more} more`}</>}
                {used.kind === "ended" && used.label}
                {used.kind === "none" && "Not used yet"}
              </span>
            </>
          )}
        </p>
        <div className="mt-auto">
          <NoteRow template={t} usage={usage} canFix={canFix} onPreview={onPreview} onMakeUtility={onMakeUtility} />
        </div>
      </div>
    </div>
  );
}
