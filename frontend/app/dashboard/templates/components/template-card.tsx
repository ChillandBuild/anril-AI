"use client";

import { useState } from "react";
import {
  Pencil,
  Trash2,
  Copy,
  Send,
  RefreshCw,
  Play,
  FileText,
  Image as ImageIcon,
} from "lucide-react";
import type { Template } from "../types";
import { STATUS_COLORS, CATEGORY_COLORS, LANGUAGES } from "../types";
import AiraId from "./aira-id";

type TemplateCardProps = {
  template: Template;
  onEdit?: (t: Template) => void;
  onDelete?: (t: Template) => void;
  onDuplicate?: (t: Template) => void;
  onSend?: (t: Template) => void;
  onSync?: (t: Template) => void;
};

/* ── helpers ─────────────────────────────────────────────────── */

function renderMiniPreview(text: string): string {
  return text.replace(/\{\{(\d+)\}\}/g, "[$1]");
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function langLabel(code: string): string {
  return LANGUAGES.find((l) => l.code === code)?.label ?? code.toUpperCase();
}

function mediaType(t: Template): "IMAGE" | "VIDEO" | "DOCUMENT" | null {
  const m = (t.header_media_type ?? "").toUpperCase();
  return m === "IMAGE" || m === "VIDEO" || m === "DOCUMENT" ? m : null;
}

function headerTextLine(t: Template): string {
  return !mediaType(t) && t.header_text ? renderMiniPreview(t.header_text) : "";
}

/* ── sub-component: media header (image / video / document) ──── */

// A media-header template is sent with its media on top, so the card shows it
// too. A Meta upload handle ("4::...") isn't a URL, and Meta's example links
// expire, so anything that can't load falls back to a labelled placeholder.
function CardHeader({ template: t }: { template: Template }) {
  const [failed, setFailed] = useState(false);
  const type = mediaType(t);
  if (!type) return null;
  const src = t.header_media_url && /^https?:/.test(t.header_media_url) ? t.header_media_url : undefined;

  if (type === "IMAGE" && src && !failed) {
    return (
      /* eslint-disable-next-line @next/next/no-img-element */
      <img
        src={src}
        alt={`${t.name} header image`}
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
        className="block w-full h-auto max-h-48 object-contain bg-[#F0F2F5]"
      />
    );
  }

  const Icon = type === "VIDEO" ? Play : type === "DOCUMENT" ? FileText : ImageIcon;
  const label = type === "VIDEO" ? "Video header" : type === "DOCUMENT" ? "Document header" : "Image header";
  return (
    <div className={`w-full h-16 flex items-center justify-center gap-1.5 ${type === "VIDEO" ? "bg-gray-700 text-white/80" : "bg-gray-200 text-gray-500"}`}>
      <Icon size={16} aria-hidden="true" />
      <span className="text-[10px] font-medium">{label}</span>
    </div>
  );
}

/* ── component ───────────────────────────────────────────────── */

export default function TemplateCard({
  template: t,
  onEdit,
  onDelete,
  onDuplicate,
  onSend,
  onSync,
}: TemplateCardProps) {
  const [hovered, setHovered] = useState(false);

  const statusStyle = STATUS_COLORS[t.status] ?? STATUS_COLORS.PENDING;
  const catStyle = CATEGORY_COLORS[t.category] ?? {
    bg: "bg-gray-50",
    text: "text-gray-600",
  };

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="card card-hover rounded-2xl relative overflow-hidden flex flex-col transition-all duration-200 group cursor-pointer"
      style={{ padding: 0 }}
    >
      {/* ── Mini WhatsApp preview ─────────────────── */}
      <div
        className="px-4 pt-4 pb-3 relative"
        style={{ background: "#ECE5DD" }}
      >
        {/* Subtle pattern */}
        <div
          className="absolute inset-0 opacity-[0.035] pointer-events-none"
          style={{
            backgroundImage:
              "url('https://static.whatsapp.net/rsrc.php/v3/yl/r/r_Q1kFPEKdt.png')",
            backgroundSize: "350px",
          }}
        />

        <div className="relative z-10 bg-white rounded-lg rounded-tl-[3px] shadow-sm max-w-[95%] overflow-hidden">
          <CardHeader template={t} />
          <div className="px-3 py-2">
            {headerTextLine(t) && (
              <p className="font-body text-xs font-semibold text-[#111B21] truncate mb-0.5">
                {headerTextLine(t)}
              </p>
            )}
            <p className="font-body text-xs text-[#111B21] line-clamp-3 leading-relaxed whitespace-pre-wrap break-words">
              {renderMiniPreview(t.body_text)}
            </p>
            <div className="flex justify-end mt-0.5">
              <span className="text-[9px]" style={{ color: "#8696A0" }}>
                12:00 PM ✓✓
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Info section ──────────────────────────── */}
      <div className="px-4 py-3 flex-1 flex flex-col gap-2">
        {/* Name */}
        <p className="font-label font-semibold text-ink text-sm leading-tight truncate">
          {t.name}
        </p>

        {/* Category + language badges */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold ${catStyle.bg} ${catStyle.text}`}
          >
            {t.category}
          </span>
          <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-medium bg-gray-100 text-gray-600">
            {langLabel(t.language)}
          </span>
        </div>
      </div>

      {/* ── Aira ID: sits above the hover overlay so it stays readable and
             copyable while the action buttons are showing ─────────────── */}
      {t.short_code && (
        <div className="relative z-30 px-4 pb-3">
          <AiraId code={t.short_code} size="lg" className="w-full justify-between" />
        </div>
      )}

      {/* ── Bottom: status + date ─────────────────── */}
      <div className="px-4 pb-3 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span
            className={`w-1.5 h-1.5 rounded-full ${statusStyle.dot}`}
          />
          <span
            className={`text-[11px] font-medium ${statusStyle.text}`}
          >
            {t.status}
          </span>
        </div>
        <span className="font-body text-[10px] text-ink-muted">
          {formatDate(t.submitted_at)}
        </span>
      </div>

      {/* ── Hover overlay with actions ────────────── */}
      <div
        className={`absolute inset-0 z-20 bg-black/40 backdrop-blur-[2px] flex items-center justify-center flex-wrap gap-2 p-2 transition-opacity duration-200 ${
          hovered ? "opacity-100" : "opacity-0 pointer-events-none"
        }`}
      >
        {onEdit && (
          <ActionBtn
            icon={Pencil}
            label="Edit"
            onClick={() => onEdit(t)}
          />
        )}
        {onDuplicate && (
          <ActionBtn
            icon={Copy}
            label="Duplicate"
            onClick={() => onDuplicate(t)}
          />
        )}
        {onSend && t.status === "APPROVED" && (
          <ActionBtn
            icon={Send}
            label="Send"
            onClick={() => onSend(t)}
            accent
          />
        )}
        {onSync && t.status !== "APPROVED" && (
          <ActionBtn
            icon={RefreshCw}
            label="Sync"
            onClick={() => onSync(t)}
          />
        )}
        {onDelete && (
          <ActionBtn
            icon={Trash2}
            label="Delete"
            onClick={() => onDelete(t)}
            destructive
          />
        )}
      </div>
    </div>
  );
}

/* ── sub-component: action button ────────────────────────────── */

function ActionBtn({
  icon: Icon,
  label,
  onClick,
  accent = false,
  destructive = false,
}: {
  icon: React.ElementType;
  label: string;
  onClick: () => void;
  accent?: boolean;
  destructive?: boolean;
}) {
  const bg = destructive
    ? "bg-red-500 hover:bg-red-600"
    : accent
      ? "bg-emerald-500 hover:bg-emerald-600"
      : "bg-white/90 hover:bg-white";
  const text = destructive || accent ? "text-white" : "text-ink";

  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={`flex flex-col items-center gap-1 px-3 py-2 rounded-xl ${bg} ${text} shadow-md transition-all hover:scale-105`}
      title={label}
    >
      <Icon size={16} />
      <span className="text-[9px] font-medium leading-none">{label}</span>
    </button>
  );
}
