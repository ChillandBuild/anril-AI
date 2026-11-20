/**
 * Meta's template rules, run live in the template builder.
 *
 * Every rule comes from Meta's official template docs (Components, Template review,
 * Utility templates). The backend repeats them in backend/app/services/template_rules.py.
 *
 * Three kinds of result:
 *  - a fix: we changed the text for the client, and say what we changed (`note`)
 *  - a blocker: something only the client can fix; Continue/Submit stay disabled
 *  - a tip: advice only, never blocking
 */
import { detectVariables } from "./types";
import type { Button } from "./types";

export type Fixed = { text: string; note: string | null };

/** One thing that stops the template from going to Meta. `fieldId` is focused by "Fix N things". */
export type Blocker = { fieldId: string; message: string; inline: boolean; fix?: "renumber" };

// Built with RegExp(): the project targets ES5, which rejects the `u` flag in a literal.
const EMOJI = new RegExp("[\\p{Extended_Pictographic}\\u{1F1E6}-\\u{1F1FF}\\uFE0F\\u200D]", "gu");
const NOT_LABEL_CHAR = new RegExp("[^\\p{L}\\p{N}\\p{M} ]", "gu");
const VAR_AT_START = /^\{\{\d+\}\}/;
const VAR_AT_END = /\{\{\d+\}\}$/;

function hasEmoji(text: string): boolean {
  return text.replace(EMOJI, "") !== text;
}

/* ── automatic fixes ─────────────────────────────────────────── */

/** `{{ 3 }}` → `{{3}}`, so Meta reads it as a variable. */
export function tidyVariables(text: string): Fixed {
  const fixed = text.replace(/\{\{\s*(\d+)\s*\}\}/g, "{{$1}}");
  return { text: fixed, note: fixed !== text ? "Removed the spaces inside a variable so Meta reads it." : null };
}

/** Headers can't hold emoji or formatting symbols (* _ ~ `). */
export function cleanHeader(text: string): Fixed {
  return cleanPlainText(text, "headers");
}

/** Footers are plain text too: no emoji or formatting symbols. */
export function cleanFooter(text: string): Fixed {
  return cleanPlainText(text, "footers");
}

function cleanPlainText(text: string, where: string): Fixed {
  const hadEmoji = hasEmoji(text);
  const hadSymbols = /[*_~`]/.test(text);
  if (!hadEmoji && !hadSymbols) return { text, note: null };
  const fixed = text.replace(EMOJI, "").replace(/[*_~`]/g, "").replace(/ {2,}/g, " ");
  const what = [hadSymbols && "formatting symbols", hadEmoji && "emoji"].filter(Boolean).join(" and ");
  return { text: fixed, note: `Removed ${what}. WhatsApp doesn't allow them in ${where}.` };
}

/** Button labels: letters, numbers and spaces only. */
export function cleanButtonLabel(text: string): Fixed {
  const fixed = text.replace(EMOJI, "").replace(NOT_LABEL_CHAR, "").replace(/ {2,}/g, " ");
  return {
    text: fixed,
    note: fixed !== text ? "Removed emoji and symbols. Button labels can only use letters and numbers." : null,
  };
}

/** Phone numbers: digits only (spaces, dashes and brackets dropped quietly). */
export function cleanPhone(text: string): string {
  return text.replace(/\D/g, "");
}

/** Website links must start with https://. Runs when the field loses focus. */
export function fixUrl(text: string): Fixed {
  const url = text.trim();
  if (!url) return { text: url, note: null };
  if (/^http:\/\//i.test(url)) return { text: url.replace(/^http:/i, "https:"), note: "Changed http to https." };
  if (!/^https:\/\//i.test(url)) return { text: `https://${url}`, note: "Added https:// at the start." };
  return { text: url, note: null };
}

/** Renumber variables in order of appearance; `moved` maps old number → new number. */
export function renumberVariables(text: string): { text: string; moved: Record<number, number> } {
  const moved: Record<number, number> = {};
  let next = 0;
  const fixed = text.replace(/\{\{(\d+)\}\}/g, (_m, n: string) => {
    const old = Number(n);
    if (!(old in moved)) moved[old] = ++next;
    return `{{${moved[old]}}}`;
  });
  return { text: fixed, moved };
}

/** Quick replies must sit together. Same order the backend sends: other buttons first, then quick replies. */
export function groupQuickReplies(buttons: Button[]): { buttons: Button[]; note: string | null } {
  const qrIndexes = buttons.flatMap((b, i) => (b.type === "QUICK_REPLY" ? [i] : []));
  const together = qrIndexes.every((idx, k) => k === 0 || idx === qrIndexes[k - 1] + 1);
  if (together) return { buttons, note: null };
  const grouped = [...buttons.filter((b) => b.type !== "QUICK_REPLY"), ...buttons.filter((b) => b.type === "QUICK_REPLY")];
  return { buttons: grouped, note: "Moved the quick replies together. WhatsApp requires them side by side." };
}

/* ── blockers ─────────────────────────────────────────────────── */

export function bodyBlockers(text: string, fieldId: string): Blocker[] {
  const t = text.trim();
  if (!t) return [{ fieldId, message: "Write the message", inline: false }];
  const out: Blocker[] = [];
  const vars = detectVariables(t);
  if (VAR_AT_START.test(t)) {
    out.push({ fieldId, inline: true, message: `Start with a word before {{${vars[0] ?? 1}}}. Meta rejects templates that open with a variable.` });
  }
  if (VAR_AT_END.test(t)) {
    out.push({ fieldId, inline: true, message: "Add a word after the last variable. Meta rejects templates that end with one." });
  }
  if (vars.length && vars.some((v, i) => v !== i + 1)) {
    out.push({ fieldId, inline: true, fix: "renumber", message: "Variables must count up from {{1}} with no gaps." });
  }
  const named = t.match(/\{\{(?!\d+\}\})[^{}]*\}\}/);
  if (named) {
    out.push({ fieldId, inline: true, message: `${named[0]} isn't a numbered variable. Use "Insert Variable" instead.` });
  }
  if ((t.match(/\{\{/g) ?? []).length !== (t.match(/\}\}/g) ?? []).length) {
    out.push({ fieldId, inline: true, message: "A variable is missing a brace. Each one looks like {{1}}." });
  }
  return out;
}

export function headerBlockers(text: string, fieldId: string): Blocker[] {
  const vars = detectVariables(text);
  if (vars.length > 1) return [{ fieldId, inline: true, message: "The header can hold only one variable." }];
  if (vars.length === 1 && vars[0] !== 1) return [{ fieldId, inline: true, message: "The header variable must be {{1}}." }];
  return [];
}

export function footerBlockers(text: string, fieldId: string): Blocker[] {
  return text.includes("{{")
    ? [{ fieldId, inline: true, message: "The footer can't contain variables. Move it into the message body." }]
    : [];
}

/** Variables in `text` with no sample yet. `idPrefix` + number is each sample input's id. */
export function sampleBlockers(text: string, samples: Record<number, string>, idPrefix: string): Blocker[] {
  return detectVariables(text)
    .filter((n) => !(samples[n] ?? "").trim())
    .map((n) => ({ fieldId: `${idPrefix}${n}`, inline: true, message: `Add a sample for {{${n}}}.` }));
}

/** Per-button problems, keyed so the builder can show each under the right field. */
export function buttonBlockers(buttons: Button[]): Blocker[] {
  const out: Blocker[] = [];
  const seen = new Set<string>();
  buttons.forEach((b, i) => {
    const label = b.text.trim().toLowerCase();
    if (!label) out.push({ fieldId: `btn-label-${i}`, inline: true, message: "Give this button a label." });
    else if (seen.has(label)) out.push({ fieldId: `btn-label-${i}`, inline: true, message: "Two buttons have the same label. Change one of them." });
    seen.add(label);
    if (b.type === "URL") {
      const url = (b.url ?? "").trim();
      const count = (url.match(/\{\{\d+\}\}/g) ?? []).length;
      if (!url) out.push({ fieldId: `btn-url-${i}`, inline: false, message: "Add the website link" });
      else if (count > 1) out.push({ fieldId: `btn-url-${i}`, inline: true, message: "A link can hold only one variable." });
      else if (count === 1 && !VAR_AT_END.test(url)) out.push({ fieldId: `btn-url-${i}`, inline: true, message: "Put the variable at the very end of the link." });
      else if (count === 1 && !(b.url_example ?? "").trim()) out.push({ fieldId: `btn-urlsample-${i}-1`, inline: true, message: "Add a sample for the link variable." });
    }
    if ((b.type === "PHONE_NUMBER" || b.type === "WHATSAPP_CALL") && !(b.phone ?? "").trim()) {
      out.push({ fieldId: `btn-phone-${i}`, inline: false, message: "Add the phone number" });
    }
    if (b.type === "FLOW" && !(b.form_ref ?? "").trim()) {
      out.push({ fieldId: `btn-label-${i}`, inline: false, message: "Pick the form this button opens" });
    }
  });
  return out;
}

/* ── tips ─────────────────────────────────────────────────────── */

/**
 * Meta rejects templates with "too many variables relative to the message length" but
 * publishes no number. Providers report a floor of 3 words per variable plus 1; below
 * that we show a calm tip and never block.
 */
export function shortTemplateTip(text: string): string | null {
  const vars = detectVariables(text);
  if (!vars.length) return null;
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return words < 3 * vars.length + 1
    ? "Meta may reject very short templates with many variables. A few more words around them usually helps."
    : null;
}

export const UTILITY_TIP =
  "Utility templates must not contain offers or promotions. If they do, Meta moves them to Marketing, which costs more.";
