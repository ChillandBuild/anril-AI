// Pure helpers for the QR & links page: print sizes, wording, form checks.

import type { QrStats } from "@/lib/qrLinksApi";

export const NAME_MAX = 80;
export const MESSAGE_MAX = 300;

export type PrintSizeKey = "table" | "counter" | "wall" | "sticker";

export interface PrintSize {
  key: PrintSizeKey;
  label: string;
  /** "A6" etc, shown next to the label. */
  paper: string;
  widthMm: number;
  heightMm: number;
  /** Side of the QR square on the page. */
  qrMm: number;
  /** Font sizes in points: place name, "Scan to chat" line, business name. */
  placePt: number;
  scanPt: number;
  businessPt: number;
}

export const PRINT_SIZES: PrintSize[] = [
  { key: "table", label: "Table card", paper: "A6", widthMm: 105, heightMm: 148, qrMm: 70, placePt: 22, scanPt: 14, businessPt: 16 },
  { key: "counter", label: "Counter stand", paper: "A5", widthMm: 148, heightMm: 210, qrMm: 100, placePt: 30, scanPt: 20, businessPt: 22 },
  { key: "wall", label: "Wall poster", paper: "A4", widthMm: 210, heightMm: 297, qrMm: 150, placePt: 40, scanPt: 28, businessPt: 30 },
  { key: "sticker", label: "Sticker", paper: "5 cm", widthMm: 50, heightMm: 50, qrMm: 30, placePt: 9, scanPt: 8, businessPt: 9 },
];

export function printSize(key: PrintSizeKey): PrintSize {
  return PRINT_SIZES.find((s) => s.key === key) ?? PRINT_SIZES[0];
}

/** CSS that makes the browser print only the sheet, on a page of exactly that size. */
export function printCss(size: PrintSize): string {
  const w = `${size.widthMm}mm`;
  const h = `${size.heightMm}mm`;
  return [
    `@page { size: ${w} ${h}; margin: 0; }`,
    "@media screen { .qr-print-sheet { display: none !important; } }",
    "@media print {",
    "  html, body { margin: 0 !important; padding: 0 !important; background: #fff !important; }",
    "  body > *:not(.qr-print-sheet) { display: none !important; }",
    "  body * { visibility: hidden !important; }",
    "  .qr-print-sheet, .qr-print-sheet * { visibility: visible !important; }",
    `  .qr-print-sheet { position: fixed !important; left: 0; top: 0; width: ${w} !important; height: ${h} !important; margin: 0 !important; display: flex !important; transform: none !important; }`,
    "}",
  ].join("\n");
}

export function defaultFirstMessage(placeName: string): string {
  const name = placeName.trim();
  return name ? `Hi, I'm at ${name}` : "Hi";
}

export interface QrFormValues {
  name: string;
  first_message: string;
}

/** Plain-words problems with the form, keyed by field. Empty object = fine. */
export function validateQrForm(v: QrFormValues): Partial<Record<keyof QrFormValues, string>> {
  const errors: Partial<Record<keyof QrFormValues, string>> = {};
  const name = v.name.trim();
  const msg = v.first_message.trim();
  if (!name) errors.name = "Give this QR a name, like the place it will hang.";
  else if (name.length > NAME_MAX) errors.name = `Use at most ${NAME_MAX} letters.`;
  if (!msg) errors.first_message = "Write the first message the customer will send.";
  else if (msg.length > MESSAGE_MAX) errors.first_message = `Use at most ${MESSAGE_MAX} letters.`;
  return errors;
}

export function rupees(paise: number): string {
  return "₹" + Math.round(paise / 100).toLocaleString("en-IN");
}

export interface StatCell {
  label: string;
  value: string;
}

/** Scanned · Chats · New customers · Paid (₹…). The ₹ amount shows only when the server sent it. */
export function statCells(s: QrStats): StatCell[] {
  const paid = s.paid_paise === undefined ? String(s.paid_orders) : `${s.paid_orders} (${rupees(s.paid_paise)})`;
  return [
    { label: "Scanned", value: String(s.opens) },
    { label: "Chats", value: String(s.chats) },
    { label: "New customers", value: String(s.new_customers) },
    { label: "Paid", value: paid },
  ];
}

/** A safe file name for the PNG download: "Table 4 / Patio" -> "qr-table-4-patio-ABCDE.png". */
export function pngFileName(name: string, code: string): string {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
  return `qr-${slug || "code"}-${code}.png`;
}

const PX_PER_MM = 3.78; // CSS reference pixels in a millimetre

/** How far to shrink the on-screen preview so the whole sheet fits the box it sits in (never grows past 1). */
export function previewScale(containerPx: number, size: PrintSize): number {
  if (!(containerPx > 0)) return 1;
  return Math.min(1, containerPx / (size.widthMm * PX_PER_MM));
}

export { PX_PER_MM };

/** Where Tab should go inside a dialog with `count` focusable things: wraps at both ends, and pulls
 *  focus back in (index 0 / last) when it has escaped. `current` is -1 when focus is outside. */
export function trapTabTarget(count: number, current: number, shift: boolean): number | null {
  if (count <= 0) return null;
  if (current < 0) return shift ? count - 1 : 0;
  if (shift && current === 0) return count - 1;
  if (!shift && current === count - 1) return 0;
  return null; // let the browser move focus normally
}
