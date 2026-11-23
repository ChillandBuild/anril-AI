import type { Button, Template } from "./types";

/**
 * Hands a ready-made draft to the Create Template builder: "Copy", "Change to Utility"
 * and "Write with AI" all open /dashboard/templates/new already filled in.
 * Kept for one page load only (sessionStorage), and read once.
 */
const PREFILL_KEY = "templates:prefill";

export type TemplatePrefill = {
  name: string;
  category: "MARKETING" | "UTILITY" | "AUTHENTICATION";
  language: string;
  headerType: "NONE" | "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT";
  headerText: string;
  bodyText: string;
  footerText: string;
  buttons: Button[];
  /** Shown at the top of the builder, e.g. "Copied from payment_reminder". */
  source: string;
};

const CATEGORIES = ["MARKETING", "UTILITY", "AUTHENTICATION"] as const;
const HEADERS = ["NONE", "TEXT", "IMAGE", "VIDEO", "DOCUMENT"] as const;

function asCategory(v: string | undefined): TemplatePrefill["category"] {
  const up = (v ?? "").toUpperCase();
  return (CATEGORIES as readonly string[]).includes(up) ? (up as TemplatePrefill["category"]) : "MARKETING";
}

function asHeader(t: Pick<Template, "header_media_type" | "header_text">): TemplatePrefill["headerType"] {
  const up = (t.header_media_type ?? "").toUpperCase();
  if ((HEADERS as readonly string[]).includes(up) && up !== "NONE") return up as TemplatePrefill["headerType"];
  return t.header_text ? "TEXT" : "NONE";
}

/** Meta names: small letters, digits and _ only, at most 512 characters. */
export function safeTemplateName(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "")
    .slice(0, 512);
}

/** A copy of an existing template. A media header needs a fresh upload: Meta's file handle can't be reused. */
export function prefillFromTemplate(
  t: Template,
  opts: { category?: TemplatePrefill["category"]; suffix?: string; source?: string } = {},
): TemplatePrefill {
  return {
    name: safeTemplateName(`${t.name}_${opts.suffix ?? "copy"}`),
    category: opts.category ?? asCategory(t.category),
    language: t.language || "en",
    headerType: asHeader(t),
    headerText: t.header_text ?? "",
    bodyText: t.body_text ?? "",
    footerText: t.footer_text ?? "",
    buttons: (t.buttons ?? []).map((b) => ({ ...b })),
    source: opts.source ?? `Copied from ${t.name}`,
  };
}

export function savePrefill(p: TemplatePrefill): void {
  try {
    sessionStorage.setItem(PREFILL_KEY, JSON.stringify(p));
  } catch {
    // storage blocked: the builder simply opens empty
  }
}

/** Reads the waiting draft and clears it, so a refresh starts clean. */
export function takePrefill(): TemplatePrefill | null {
  try {
    const raw = sessionStorage.getItem(PREFILL_KEY);
    sessionStorage.removeItem(PREFILL_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as Partial<TemplatePrefill>;
    if (typeof p.bodyText !== "string") return null;
    return {
      name: safeTemplateName(p.name ?? ""),
      category: asCategory(p.category),
      language: p.language || "en",
      headerType: (HEADERS as readonly string[]).includes(p.headerType ?? "") ? (p.headerType as TemplatePrefill["headerType"]) : "NONE",
      headerText: p.headerText ?? "",
      bodyText: p.bodyText,
      footerText: p.footerText ?? "",
      buttons: Array.isArray(p.buttons) ? p.buttons : [],
      source: p.source ?? "",
    };
  } catch {
    return null;
  }
}
