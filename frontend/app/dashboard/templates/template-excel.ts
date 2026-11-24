import type { Template, TemplateUsage } from "./types";
import { languageName } from "./types";
import { statusNote, usedInText, liveUsage } from "./template-filters";

/** What the spreadsheet calls a template's type (Marketing / Utility / Authentication). */
export function typeName(category: string): string {
  return category.charAt(0) + category.slice(1).toLowerCase();
}

export function buttonsText(t: Template): string {
  return (t.buttons ?? [])
    .map((b) => {
      if (b.type === "URL") return `${b.text} (${b.url || ""})`;
      if (b.type === "PHONE_NUMBER") return `${b.text} (${b.phone || ""})`;
      return b.text || b.autofill_text || b.type;
    })
    .join(" | ");
}

export const DOWNLOAD_HEADER = ["name", "type", "language", "status", "message", "footer", "buttons", "used in", "reason"];

/** Every template, one row each: the "Download all" sheet. */
export function downloadRows(templates: Template[], usage: TemplateUsage): string[][] {
  return templates.map((t) => [
    t.name,
    typeName(t.category),
    languageName(t.language),
    t.status,
    t.body_text,
    t.footer_text ?? "",
    buttonsText(t),
    liveUsage(usage[t.id]).map((e) => e.label).join(", ") || usedInText(usage[t.id]).replace(/^Used in: /, ""),
    statusNote(t)?.text ?? "",
  ]);
}

type Sheet = { header: string[]; rows: string[][]; widths: number[]; name: string; file: string };

/** Writes one .xlsx in the browser with the xlsx library the page already uses. */
export async function saveSheet({ header, rows, widths, name, file }: Sheet): Promise<void> {
  const XLSX = await import("xlsx");
  const ws = XLSX.utils.aoa_to_sheet([header, ...rows]);
  ws["!cols"] = header.map((h, col) => ({
    wch: Math.min(
      widths[col] ?? 30,
      Math.max(h.length, ...rows.map((r) => Math.max(0, ...(r[col] ?? "").split("\n").map((l) => l.length)))) + 2,
    ),
  }));
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, name);
  XLSX.writeFile(wb, file);
}

/** The templates given (the Templates page passes what its filters show), one row each. */
export function saveAllTemplates(templates: Template[], usage: TemplateUsage, filtered = false): Promise<void> {
  return saveSheet({
    header: DOWNLOAD_HEADER, rows: downloadRows(templates, usage), widths: [40, 14, 12, 12, 70, 30, 40, 40, 60],
    name: "Templates", file: `whatsapp-templates-${filtered ? "filtered-" : ""}${new Date().toISOString().slice(0, 10)}.xlsx`,
  });
}

// ── the upload check (POST /api/v1/templates/bulk/check, /bulk/recheck, /bulk/submit) ─────
// The sample file itself comes from GET /bulk/sample: it has Excel dropdowns the browser can't write.

export type BulkButtonKind = "URL" | "PHONE_NUMBER" | "QUICK_REPLY";
export type BulkButton = { type: BulkButtonKind | ""; text: string; value: string };
export type BulkIssue = { field: string; text: string };

export type BulkRow = {
  row: number;
  name: string;
  type: string | null;
  language: string | null;
  header: string;
  header_example: string;
  body: string;
  /** Example {{1}} .. {{5}}, always 5 long. */
  examples: string[];
  footer: string;
  buttons: BulkButton[];
  /** Each problem with the field it belongs to (name, type, language, header, header_example, body,
   * example_1..5, footer, button_1..3), so the review screen can mark that field. */
  issues: BulkIssue[];
  problems: string[];
  status: "ready" | "need_fix" | "exists";
};

export type BulkCounts = { ready: number; need_fix: number; exists: number };

export type BulkResult = { row: number; name: string; language: string | null; status: "sent" | "refused" | "skipped"; reason?: string };

export const EXAMPLE_SLOTS = 5;
export const BUTTON_SLOTS = 3;
export const BUTTON_KINDS: { value: BulkButtonKind; label: string }[] = [
  { value: "URL", label: "Link" },
  { value: "PHONE_NUMBER", label: "Call" },
  { value: "QUICK_REPLY", label: "Quick reply" },
];

/** The {{n}} numbers a text uses, in order. */
export function variablesIn(text: string): number[] {
  return Array.from(new Set(Array.from(text.matchAll(/\{\{(\d+)\}\}/g), (m) => Number(m[1])))).sort((a, b) => a - b);
}

/** The problems that belong to one field. */
export function issuesFor(row: BulkRow, field: string): string[] {
  return row.issues.filter((i) => i.field === field).map((i) => i.text);
}

/** Three button slots, filled from the row's buttons. */
export function buttonSlots(row: BulkRow): BulkButton[] {
  const given = row.buttons.slice(0, BUTTON_SLOTS);
  return [...given, ...Array.from({ length: BUTTON_SLOTS - given.length }, () => ({ type: "" as const, text: "", value: "" }))];
}

/** What the review screen sends back to /bulk/recheck and /bulk/submit for one row. */
export function rowForCheck(row: BulkRow) {
  const examples = [...row.examples, ...Array(EXAMPLE_SLOTS).fill("")].slice(0, EXAMPLE_SLOTS);
  return {
    row: row.row,
    name: row.name,
    type: row.type ?? "",
    language: row.language ?? "",
    header: row.header,
    header_example: row.header_example,
    body: row.body,
    examples,
    footer: row.footer,
    buttons: buttonSlots(row).filter((b) => b.type || b.text || b.value),
  };
}

/** Props for the WhatsApp preview: header, body with the examples in place of {{n}}, footer, buttons. */
export function previewOf(row: BulkRow) {
  return {
    headerType: (row.header ? "TEXT" : "NONE") as "TEXT" | "NONE",
    headerText: row.header || undefined,
    headerSample: row.header_example || undefined,
    bodyText: row.body || " ",
    bodySamples: Object.fromEntries(row.examples.map((v, i) => [i + 1, v]).filter(([, v]) => v)),
    footerText: row.footer || undefined,
    buttons: row.buttons
      .filter((b) => b.type && b.text)
      .map((b) => ({ type: b.type, text: b.text, url: b.type === "URL" ? b.value : undefined, phone: b.type === "PHONE_NUMBER" ? b.value : undefined })),
  };
}

/** "4 ready · 2 need a fix · 1 already exists", leaving out the zeros. */
export function countsText(c: BulkCounts): string {
  const parts: string[] = [];
  if (c.ready) parts.push(`${c.ready} ready`);
  if (c.need_fix) parts.push(`${c.need_fix} need a fix`);
  if (c.exists) parts.push(`${c.exists} already ${c.exists === 1 ? "exists" : "exist"}`);
  return parts.join(" · ") || "Nothing found";
}
