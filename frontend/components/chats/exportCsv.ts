/** CSV downloads for the Chats pages (Archived, Needs you). Built in the browser from rows the
 *  viewer can already see; the Export buttons are owner-only, like Segments' export. */

import { isPhoneFormula } from "@/lib/csvPhone";

export type CsvColumn<T> = { header: string; value: (row: T) => string | number | null | undefined };

/** A cell a spreadsheet would run as a formula (=, @, or +/- before a non-digit) gets a leading
 *  apostrophe. Customer names and messages are typed by customers, so this matters. Phone
 *  numbers like +919876543210 are left alone. */
function safeCell(value: string): string {
  if (isPhoneFormula(value)) return value;
  if (/^[=@\t\r]/.test(value) || /^[+-][^\d\s]/.test(value)) return `'${value}`;
  return value;
}

function quote(value: string): string {
  return /[",\n\r]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export function toCsv<T>(rows: T[], columns: CsvColumn<T>[]): string {
  const lines = [columns.map((c) => quote(c.header)).join(",")];
  for (const row of rows) {
    lines.push(columns.map((c) => quote(safeCell(String(c.value(row) ?? "")))).join(","));
  }
  // Byte-order mark so Excel opens Tamil and other scripts correctly.
  return "﻿" + lines.join("\r\n");
}

export function downloadCsv<T>(fileName: string, rows: T[], columns: CsvColumn<T>[]): void {
  const blob = new Blob([toCsv(rows, columns)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** "2026-11-17" for file names. */
export function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** "17 Nov 2026, 14:05" in India time, for date columns. */
export function istDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata",
  });
}

const SEGMENT_LABEL: Record<string, string> = { A: "Hot", B: "Warm", C: "Cold", D: "Not interested" };
export function segmentLabel(segment: string | null | undefined): string {
  return segment ? SEGMENT_LABEL[segment] ?? segment : "";
}

export function channelLabel(source: string | null | undefined): string {
  if (source === "instagram") return "Instagram";
  if (source === "facebook") return "Facebook";
  if (source === "telegram") return "Telegram";
  return "WhatsApp";
}
