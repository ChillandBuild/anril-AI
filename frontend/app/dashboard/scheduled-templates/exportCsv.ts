/** A cell that a spreadsheet could run as a formula gets a leading apostrophe. Phone numbers (+91 98765 43210) stay as they are. */
function safeCell(value: string): string {
  if (/^[=@\t\r]/.test(value) || /^[+-](?![\d\s]+$)/.test(value)) return `'${value}`;
  return value;
}

function quote(value: string): string {
  const text = safeCell(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** CSV text with a byte-order mark, so Excel reads Tamil names and templates correctly. */
export function buildCsv(header: string[], rows: string[][]): string {
  return "﻿" + [header, ...rows].map((row) => row.map(quote).join(",")).join("\r\n");
}

export function downloadCsv(filename: string, csv: string) {
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
