/**
 * Text helpers for the template body box: insert at the cursor, WhatsApp bold / italic,
 * and a reader that finds the same bold / italic WhatsApp will show (used by the live preview).
 *
 * WhatsApp formatting: *bold*, _italic_. The marker sits right against the words, so
 * "* hi *" is not bold.
 */

export type EditResult = { value: string; selStart: number; selEnd: number };

/** Put `text` where the cursor is (replacing any selection). null = would go over maxLength. */
export function insertAt(value: string, start: number, end: number, text: string, maxLength: number): EditResult | null {
  const next = value.slice(0, start) + text + value.slice(end);
  if (next.length > maxLength) return null;
  const pos = start + text.length;
  return { value: next, selStart: pos, selEnd: pos };
}

/**
 * Wrap the selection in a marker (* or _). Selecting already-wrapped text, or text sitting
 * between two markers, takes the marker off again. Spaces at the edges of the selection stay
 * outside the marker, because WhatsApp ignores "* hi *". null = would go over maxLength.
 */
export function toggleWrap(value: string, start: number, end: number, marker: string, maxLength: number): EditResult | null {
  const picked = value.slice(start, end);
  const lead = picked.length - picked.replace(/^\s+/, "").length;
  const trail = picked.length - picked.replace(/\s+$/, "").length;
  const s = start + lead;
  const e = Math.max(s, end - trail);
  const inner = value.slice(s, e);

  if (!inner) {
    // Nothing selected: drop a pair and leave the cursor between them.
    const next = value.slice(0, start) + marker + marker + value.slice(end);
    if (next.length > maxLength) return null;
    return { value: next, selStart: start + 1, selEnd: start + 1 };
  }
  if (inner.length >= 2 && inner.charAt(0) === marker && inner.charAt(inner.length - 1) === marker) {
    const bare = inner.slice(1, -1);
    return { value: value.slice(0, s) + bare + value.slice(e), selStart: s, selEnd: s + bare.length };
  }
  if (s > 0 && value.charAt(s - 1) === marker && value.charAt(e) === marker) {
    return { value: value.slice(0, s - 1) + inner + value.slice(e + 1), selStart: s - 1, selEnd: e - 1 };
  }
  const next = value.slice(0, s) + marker + inner + marker + value.slice(e);
  if (next.length > maxLength) return null;
  return { value: next, selStart: s + 1, selEnd: e + 1 };
}

/* ── reading bold / italic, for the preview ──────────────────── */

export type Segment = { kind: "text" | "bold" | "italic"; text: string };

const WORD_CHAR = new RegExp("[\\p{L}\\p{N}]", "u");
const isWord = (ch: string) => ch !== "" && WORD_CHAR.test(ch);
const isSpace = (ch: string) => ch === "" || /\s/.test(ch);

/** Split text into plain / bold / italic pieces the way WhatsApp reads *bold* and _italic_. */
export function formatSegments(text: string): Segment[] {
  const out: Segment[] = [];
  let plain = "";
  const flush = () => {
    if (plain) out.push({ kind: "text", text: plain });
    plain = "";
  };
  let i = 0;
  while (i < text.length) {
    const ch = text.charAt(i);
    if ((ch === "*" || ch === "_") && !isWord(text.charAt(i - 1)) && !isSpace(text.charAt(i + 1)) && text.charAt(i + 1) !== ch) {
      let close = -1;
      for (let j = i + 2; j < text.length; j++) {
        const c = text.charAt(j);
        if (c === "\n") break;
        if (c === ch && !isSpace(text.charAt(j - 1)) && !isWord(text.charAt(j + 1))) {
          close = j;
          break;
        }
      }
      if (close > 0) {
        flush();
        out.push({ kind: ch === "*" ? "bold" : "italic", text: text.slice(i + 1, close) });
        i = close + 1;
        continue;
      }
    }
    plain += ch;
    i += 1;
  }
  flush();
  return out;
}
