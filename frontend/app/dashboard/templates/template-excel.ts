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

export const SAMPLE_HEADER = ["name", "type", "language", "message", "sample values", "footer", "button text", "button link"];

export const SAMPLE_ROWS: string[][] = [
  [
    "festival_offer", "Marketing", "English",
    "Hi {{1}}, flat {{2}} off on all sarees this week at our shop.", "Priya, 20%", "Thank you", "Shop now", "https://example.com/shop",
  ],
  [
    "order_ready", "Utility", "Tamil",
    "வணக்கம் {{1}}, உங்கள் ஆர்டர் {{2}} தயாராக உள்ளது.", "Priya, D-1047", "", "", "",
  ],
];

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

export function saveSampleFile(): Promise<void> {
  return saveSheet({
    header: SAMPLE_HEADER, rows: SAMPLE_ROWS, widths: [30, 12, 12, 70, 28, 24, 20, 40],
    name: "Templates", file: "sample_templates.xlsx",
  });
}

export function saveAllTemplates(templates: Template[], usage: TemplateUsage): Promise<void> {
  return saveSheet({
    header: DOWNLOAD_HEADER, rows: downloadRows(templates, usage), widths: [40, 14, 12, 12, 70, 30, 40, 40, 60],
    name: "Templates", file: `whatsapp-templates-${new Date().toISOString().slice(0, 10)}.xlsx`,
  });
}

// ── the upload check (POST /api/v1/templates/bulk/check and /bulk/submit) ─────

export type BulkRow = {
  row: number;
  name: string;
  type: string | null;
  language: string | null;
  message: string;
  samples: string[];
  footer: string;
  button_text: string;
  button_link: string;
  problems: string[];
  status: "ready" | "need_fix" | "exists";
};

export type BulkCounts = { ready: number; need_fix: number; exists: number };

export type BulkResult = { row: number; name: string; language: string | null; status: "sent" | "refused" | "skipped"; reason?: string };

/** "4 ready · 2 need a fix · 1 already exists", leaving out the zeros. */
export function countsText(c: BulkCounts): string {
  const parts: string[] = [];
  if (c.ready) parts.push(`${c.ready} ready`);
  if (c.need_fix) parts.push(`${c.need_fix} need a fix`);
  if (c.exists) parts.push(`${c.exists} already ${c.exists === 1 ? "exists" : "exist"}`);
  return parts.join(" · ") || "Nothing found";
}
