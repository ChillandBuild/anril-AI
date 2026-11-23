// Demo-request form logic, kept apart from the component so it can be read and tested alone.
//
// Leads go to Anril's own tenant through the public Auto-Messages intake,
// POST /api/v1/auto-messages/in/{token} (backend/app/routes/auto_messages.py). The
// browser posts form fields directly, a CORS "simple request" with no preflight,
// exactly like the hosted form.js snippet, so the per-IP rate limit counts each
// visitor. name and phone go on the lead; company and industry are kept as
// `extra` on the send-log row.

import { CONTACT_EMAIL, INDUSTRIES, MORE_INDUSTRIES } from "./content";

export const INDUSTRY_OPTIONS: readonly string[] = [...INDUSTRIES, ...MORE_INDUSTRIES].map((i) => i.name).concat("Other");

export type DemoFields = { name: string; phone: string; company: string; industry: string };
export type DemoErrors = Partial<Record<keyof DemoFields, string>>;
export type SubmitResult = { ok: true } | { ok: false; message: string };

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://aira-ai-5tfr.onrender.com";
const FORM_TOKEN = process.env.NEXT_PUBLIC_ANRIL_FORM_TOKEN || "";
const TIMEOUT_MS = 20_000;
const LINK_RE = /(https?:\/\/|www\.)/i;

/** Mirrors the backend's phone normaliser (routes/upload.py _normalize_phone), stricter on bare numbers. */
export function phoneIsValid(raw: string): boolean {
  const trimmed = raw.trim();
  const digits = trimmed.replace(/\D/g, "").replace(/^0+/, "");
  if (trimmed.startsWith("+")) return digits.length >= 8 && digits.length <= 15;
  if (digits.length === 10) return /^[6-9]/.test(digits);
  if (digits.length === 12) return /^91[6-9]/.test(digits);
  return false;
}

export function validateDemo(f: DemoFields): DemoErrors {
  const errors: DemoErrors = {};
  const name = f.name.trim();
  if (!name) errors.name = "Enter your name.";
  else if (name.length > 80 || LINK_RE.test(name)) errors.name = "Enter just your name, up to 80 characters.";
  if (!f.phone.trim()) errors.phone = "Enter your phone number.";
  else if (!phoneIsValid(f.phone)) errors.phone = "Enter a 10-digit mobile number, or add your country code with +.";
  const company = f.company.trim();
  if (!company) errors.company = "Enter your business name.";
  else if (company.length > 120) errors.company = "Keep the business name under 120 characters.";
  if (!INDUSTRY_OPTIONS.includes(f.industry)) errors.industry = "Choose an industry.";
  return errors;
}

const FAILED = `We could not send your details. Please try again, or email ${CONTACT_EMAIL}.`;

export async function submitDemo(f: DemoFields, honeypot: string): Promise<SubmitResult> {
  if (!FORM_TOKEN) {
    return { ok: false, message: `The demo form is not connected yet. Please email ${CONTACT_EMAIL}.` };
  }
  const body = new URLSearchParams({
    name: f.name.trim(),
    phone: f.phone.trim(),
    company: f.company.trim(),
    industry: f.industry,
    event: "interested",
    page_url: window.location.href,
    _src: "form",
    _hp: honeypot,
  });
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${API_URL}/api/v1/auto-messages/in/${encodeURIComponent(FORM_TOKEN)}`, {
      method: "POST",
      body,
      signal: controller.signal,
    });
    if (res.ok) return { ok: true };
    if (res.status === 429) return { ok: false, message: "Too many tries. Please wait a few minutes and try again." };
    if (res.status === 422) return { ok: false, message: "Please check your phone number and try again." };
    return { ok: false, message: FAILED };
  } catch {
    return { ok: false, message: FAILED };
  } finally {
    window.clearTimeout(timer);
  }
}
