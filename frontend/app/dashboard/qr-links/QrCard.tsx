"use client";

import { useRef } from "react";
import { QRCodeCanvas } from "qrcode.react";
import { toast } from "sonner";
import { Archive, ArchiveRestore, Copy, Download, Pencil, Printer } from "lucide-react";
import type { QrLink } from "@/lib/qrLinksApi";
import { pngFileName, statCells } from "@/lib/qrLinks";

const btn =
  "inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary";

export function QrCard({
  link, canManage, onEdit, onPrint, onToggleArchive,
}: {
  link: QrLink;
  canManage: boolean;
  onEdit: () => void;
  onPrint: () => void;
  onToggleArchive: () => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);

  function downloadPng() {
    const canvas = wrap.current?.querySelector("canvas");
    if (!canvas) return;
    const a = document.createElement("a");
    a.href = canvas.toDataURL("image/png");
    a.download = pngFileName(link.name, link.code);
    a.click();
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(link.url);
      toast.success("Link copied");
    } catch {
      toast.error("Couldn't copy. Select the link and copy it by hand.");
    }
  }

  return (
    <li className={`rounded-card border border-border bg-white p-4 shadow-card ${link.archived ? "opacity-70" : ""}`}>
      <div className="flex gap-4">
        <div ref={wrap} className="shrink-0 rounded-xl border border-border bg-white p-2">
          {/* 512 px canvas for a sharp PNG, shown small. */}
          <QRCodeCanvas value={link.url} size={512} level="M" marginSize={2} style={{ width: 96, height: 96 }} role="img" aria-label={`QR code for ${link.name}`} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="break-words text-base font-bold text-ink">{link.name}</h3>
            {link.archived && <span className="rounded-full bg-surface-low px-2 py-0.5 text-xs font-semibold text-ink-muted">Archived</span>}
          </div>
          {link.place_name && <p className="text-sm text-ink-muted">Place: {link.place_name}</p>}
          <p className="mt-1 break-words text-sm text-ink">&ldquo;{link.first_message}&rdquo;</p>
          <p className="mt-1 break-all text-xs text-ink-muted">{link.url}</p>
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {statCells(link.stats).map((c) => (
          <div key={c.label} className="rounded-xl bg-surface-low px-3 py-2">
            <dt className="text-xs text-ink-muted">{c.label}</dt>
            <dd className="text-sm font-bold text-ink">{c.value}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={onPrint} className={btn}><Printer size={16} /> Print</button>
        <button type="button" onClick={downloadPng} className={btn}><Download size={16} /> Download PNG</button>
        <button type="button" onClick={copyLink} className={btn}><Copy size={16} /> Copy link</button>
        {canManage && <button type="button" onClick={onEdit} className={btn}><Pencil size={16} /> Edit</button>}
        {canManage && (
          <button type="button" onClick={onToggleArchive} className={btn}>
            {link.archived ? <><ArchiveRestore size={16} /> Bring back</> : <><Archive size={16} /> Archive</>}
          </button>
        )}
      </div>
    </li>
  );
}
