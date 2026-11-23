// v9.2 screen 116: after a notebook photo is read, the owner checks what we read before it becomes a list:
// type names we couldn't read, fix or remove numbers that look wrong. Pure helpers (unit-tested).

export type ScanRow = { name: string; phone: string };
export type RowCheck = { nameMissing: boolean; phoneWrong: boolean };

/** One CSV line into cells; handles "quoted, cells" and "" escapes. */
function cells(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cur += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { out.push(cur); cur = ""; }
    else cur += ch;
  }
  out.push(cur);
  return out.map((c) => c.trim());
}

/** The scan's CSV text (header with phone and maybe name) into rows. */
export function parseScanCsv(text: string): ScanRow[] {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return [];
  const head = cells(lines[0]).map((h) => h.toLowerCase());
  const pi = head.indexOf("phone");
  const ni = head.indexOf("name");
  if (pi < 0) return [];
  return lines.slice(1).map((l) => {
    const c = cells(l);
    return { name: ni >= 0 ? c[ni] ?? "" : "", phone: c[pi] ?? "" };
  });
}

/** An Indian mobile: 10 digits starting 6-9, after dropping +91 / 91 / 0 and spaces or dashes. */
export function phoneLooksWrong(phone: string): boolean {
  let d = phone.replace(/[\s\-().]/g, "");
  if (d.startsWith("+")) d = d.slice(1);
  if (!/^\d+$/.test(d)) return true;
  if (d.length === 12 && d.startsWith("91")) d = d.slice(2);
  else if (d.length === 11 && d.startsWith("0")) d = d.slice(1);
  return !/^[6-9]\d{9}$/.test(d);
}

/** A name the reader couldn't make out: empty, question marks, or an "unclear" marker. */
export function nameMissing(name: string): boolean {
  const n = name.trim();
  return !n || /\?|unclear|illegible|unreadable/i.test(n);
}

export function checkRow(row: ScanRow): RowCheck {
  return { nameMissing: nameMissing(row.name), phoneWrong: phoneLooksWrong(row.phone) };
}

/** A name read off a photo that starts like a spreadsheet formula (=, +, -, @) is kept as plain text. */
function safeName(v: string): string {
  return /^[=+\-@\t\r]/.test(v) ? `'${v}` : v;
}

function cell(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

/** Back to CSV for the normal upload. Unreadable names go as blank (never "???"). */
export function rowsToCsv(rows: ScanRow[]): string {
  return ["name,phone", ...rows.map((r) => `${cell(nameMissing(r.name) ? "" : safeName(r.name.trim()))},${cell(r.phone.trim())}`)].join("\n");
}
