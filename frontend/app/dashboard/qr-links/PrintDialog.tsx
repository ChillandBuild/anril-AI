"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { QRCodeSVG } from "qrcode.react";
import { Printer, X } from "lucide-react";
import type { QrLink } from "@/lib/qrLinksApi";
import { PRINT_SIZES, PX_PER_MM, previewScale, printCss, printSize, trapTabTarget, type PrintSize, type PrintSizeKey } from "@/lib/qrLinks";

// The print view: pick a size, see the sheet, press Print. The injected CSS makes the browser
// print only the sheet, on a page of exactly that size (@page).


function Sheet({ link, businessName, size, className, style }: { link: QrLink; businessName: string; size: PrintSize; className: string; style?: React.CSSProperties }) {
  const place = link.place_name || link.name;
  return (
    <div
      className={`${className} flex flex-col items-center justify-center bg-white text-center text-black`}
      style={{
        width: `${size.widthMm}mm`, height: `${size.heightMm}mm`, boxSizing: "border-box",
        padding: `${Math.max(2, size.widthMm * 0.04)}mm`, gap: `${Math.max(1, size.widthMm * 0.02)}mm`, overflow: "hidden", ...style,
      }}
    >
      {businessName && <div style={{ fontSize: `${size.businessPt}pt`, fontWeight: 700, lineHeight: 1.15 }}>{businessName}</div>}
      <div style={{ fontSize: `${size.scanPt}pt`, lineHeight: 1.2 }}>Scan to chat on WhatsApp</div>
      <QRCodeSVG value={link.url} size={size.qrMm * PX_PER_MM} level="M" marginSize={2} style={{ width: `${size.qrMm}mm`, height: `${size.qrMm}mm` }} />
      <div style={{ fontSize: `${size.placePt}pt`, fontWeight: 700, lineHeight: 1.15 }}>{place}</div>
    </div>
  );
}

export function PrintDialog({ link, businessName, onClose }: { link: QrLink; businessName: string; onClose: () => void }) {
  const [sizeKey, setSizeKey] = useState<PrintSizeKey>("table");
  const size = printSize(sizeKey);
  const rootRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [boxWidth, setBoxWidth] = useState(0);

  // Focus goes into the dialog on open and back to whatever opened it (the card's Print button) on close.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => opener?.focus?.();
  }, []);

  // Esc closes; Tab stays inside the dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !rootRef.current) return;
      const items = Array.from(rootRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), [href], select, textarea, [tabindex]:not([tabindex="-1"])',
      ));
      const target = trapTabTarget(items.length, items.indexOf(document.activeElement as HTMLElement), e.shiftKey);
      if (target !== null) {
        e.preventDefault();
        items[target].focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Measure the box the preview sits in, so the sheet fits at any width (390 px phones included).
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const measure = () => {
      const cs = getComputedStyle(el);
      setBoxWidth(el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const scale = previewScale(boxWidth, size);
  return (
    <div ref={rootRef} className="fixed inset-0 z-dialog flex items-start justify-center overflow-y-auto bg-black/40 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={`Print ${link.name}`}>
      <style>{printCss(size)}</style>
      {/* The copy the browser prints: straight under <body>, so no blur or scroll box can move it. */}
      {typeof document !== "undefined" && createPortal(<Sheet link={link} businessName={businessName} size={size} className="qr-print-sheet" />, document.body)}
      <div className="w-full max-w-lg rounded-card bg-white p-5 shadow-xl">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="font-display text-lg font-bold text-ink">Print &ldquo;{link.name}&rdquo;</h2>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close" className="inline-flex h-10 w-10 items-center justify-center rounded-xl text-ink-muted hover:bg-surface-low">
            <X size={18} />
          </button>
        </div>

        <fieldset className="mb-4">
          <legend className="mb-2 text-sm font-semibold text-ink">Size</legend>
          <div className="grid grid-cols-2 gap-2">
            {PRINT_SIZES.map((s) => (
              <label key={s.key} className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border px-3 py-2 text-sm ${sizeKey === s.key ? "border-primary bg-primary-50/60 font-semibold text-ink" : "border-border text-ink"}`}>
                <input type="radio" name="qr-size" value={s.key} checked={sizeKey === s.key} onChange={() => setSizeKey(s.key)} className="accent-primary" />
                <span>{s.label} <span className="text-ink-muted">({s.paper})</span></span>
              </label>
            ))}
          </div>
        </fieldset>

        <div ref={boxRef} className="mb-4 flex justify-center overflow-hidden rounded-xl bg-surface-low p-3">
          <div style={{ width: size.widthMm * PX_PER_MM * scale, height: size.heightMm * PX_PER_MM * scale }}>
            <Sheet link={link} businessName={businessName} size={size} className="qr-preview-sheet shadow-md"
              style={{ transform: `scale(${scale})`, transformOrigin: "top left" }} />
          </div>
        </div>

        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={onClose} className="inline-flex h-11 items-center rounded-xl border border-border px-4 text-sm font-semibold text-ink hover:bg-surface-low">Close</button>
          <button type="button" onClick={() => window.print()} className="inline-flex h-11 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white hover:bg-primary-dark">
            <Printer size={16} /> Print
          </button>
        </div>
      </div>
    </div>
  );
}
