import type { AutoMessageEvent, AutoMessageSend, AutoMessageVarSource, AutoMessageVariable } from "@/lib/api";

export const EVENTS: {
  id: AutoMessageEvent;
  label: string;
  when: string;
  nobody: string;
  hint: string;
}[] = [
  {
    id: "interested",
    label: "Interested",
    when: "Someone leaves their number to know more",
    nobody: "People who show interest get nothing from you.",
    hint: "Use a Marketing template: your offer and a link button.",
  },
  {
    id: "signed_up",
    label: "Signed up",
    when: "Someone creates an account or registers",
    nobody: "People who sign up get nothing from you.",
    hint: "A short welcome works best. Utility templates cost less than Marketing.",
  },
  {
    id: "purchased",
    label: "Purchased",
    when: "Someone buys, at your shop counter or online",
    nobody: "Customers who buy get no thank-you.",
    hint: "Use a Utility template (thank-you or receipt). It costs less than Marketing.",
  },
];

/** Labels of the built-in events. Custom events carry their own label from GET /events. */
export const EVENT_LABEL: Record<AutoMessageEvent, string> = {
  interested: "Interested",
  signed_up: "Signed up",
  purchased: "Purchased",
};

/** One row of "Your messages": a built-in event or one the owner added. */
export interface EventInfo {
  key: AutoMessageEvent;
  label: string;
  description: string | null;
  custom: boolean;
}

/** Plain line for an event with no message, e.g. "No message. People who sign up get nothing." */
export function nobodyLine(ev: EventInfo): string {
  const builtin = EVENTS.find((e) => e.id === ev.key);
  return `No message. ${builtin ? builtin.nobody : `Nothing is sent when ${ev.label} happens.`}`;
}

export const MAX_EVENT_KEY_LEN = 40;
const EVENT_KEY_RE = /^[a-z][a-z0-9_]{1,39}$/;

/** The code a developer sends, built from the name an owner typed. Mirrors the backend's
 *  derive_event_key: lowercase, spaces and hyphens become "_", other characters are dropped,
 *  repeats collapse. null when nothing valid is left (must start with a letter, 2-40 characters). */
export function deriveEventKey(label: string): string | null {
  const text = label
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_")
    .replace(/[^a-z0-9_]/g, "")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, MAX_EVENT_KEY_LEN)
    .replace(/^_+|_+$/g, "");
  return EVENT_KEY_RE.test(text) ? text : null;
}

export const VAR_SOURCES: { id: AutoMessageVarSource; label: string }[] = [
  { id: "first_name", label: "Customer's first name" },
  { id: "full_name", label: "Customer's full name" },
  { id: "page_url", label: "Page they came from" },
  { id: "phone", label: "Customer's number" },
  { id: "extra", label: "Value your app sends" },
  { id: "text", label: "Fixed text" },
];

/** Plain text of a variable for the WhatsApp preview, using the same sample values a real preview send uses. */
export function sampleValue(v: AutoMessageVariable): string {
  switch (v.source) {
    case "first_name":
      return "Priya";
    case "full_name":
      return "Priya";
    case "page_url":
      return "https://example.com/page";
    case "phone":
      return "98765 43210";
    case "extra":
      return (v.key ?? "").trim() || "value";
    case "text":
      return (v.value ?? "").trim() || "your text";
  }
}

export const SOURCE_LABEL: Record<AutoMessageSend["source"], string> = {
  website: "Website form",
  api: "App / API",
  store: "Shop counter",
  partner: "Partner API",
};

/** What the Event column says when an app sent a template ID directly and no event was involved. */
export const SENT_BY_APP = "Sent by your app";

/** Plain words for the codes the backend writes to auto_message_sends.reason. */
const REASON_TEXT: Record<string, string> = {
  no_rule: "No message is set up for this event yet",
  ai_auto_reply_off: "Not sent: Instant templates were off in Settings > Auto-Reply",
  // Retired checks: no new row gets these reasons, but old rows still carry them.
  duplicate: "Skipped: this person was already messaged recently",
  opted_out: "Skipped: customer had asked not to be messaged",
  template_not_approved: "The template is no longer approved by Meta",
  rule_removed_or_off: "The message was turned off before it was due",
  quiet_hours: "Held back until the morning",
  interrupted: "Interrupted before it went out",
  not_on_whatsapp: "This number is not on WhatsApp",
};

/** Meta error codes, in the same words the backend uses for preview sends. A failed live send stores
 *  Meta's raw JSON reply in reason, so these are matched from its "code" field. */
const META_CODE_TEXT: Record<string, string> = {
  "131026": "WhatsApp couldn't deliver to this number. Check that it is on WhatsApp.",
  "131030": "This number isn't on your WhatsApp test list yet.",
  "131056": "WhatsApp is slowing this account down. Try again in a minute.",
  "130429": "WhatsApp is slowing this account down. Try again in a minute.",
  "132000": "The template and its values don't match. Check the message's variables.",
  "132001": "WhatsApp can't find this template. It may have been deleted.",
  "132005": "The template and its values don't match. Check the message's variables.",
  "132012": "The template and its values don't match. Check the message's variables.",
  "190": "Your WhatsApp connection has expired. Reconnect it in Settings.",
};

const META_CODE_RE = /"code"\s*:\s*(\d+)/;
const META_MESSAGE_RE = /"message"\s*:\s*"([^"]+)"/;
const GENERIC_FAILURE = "WhatsApp could not send this message";

/** Plain-words reason for a send that didn't go out (or is waiting). */
export function reasonText(status: AutoMessageSend["status"], reason: string | null): string | null {
  if (!reason) return null;
  const known = REASON_TEXT[reason];
  if (known) return known;
  if (status !== "failed") return reason.includes("_") && !reason.includes(" ") ? reason.replace(/_/g, " ") : reason;
  const code = META_CODE_RE.exec(reason)?.[1];
  if (code && META_CODE_TEXT[code]) return META_CODE_TEXT[code];
  const message = META_MESSAGE_RE.exec(reason)?.[1];
  return message ? `WhatsApp refused it: ${message.slice(0, 150)}` : GENERIC_FAILURE;
}

export const STATUS_STYLE: Record<AutoMessageSend["status"], { label: string; cls: string }> = {
  sent: { label: "Sent", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  queued: { label: "Scheduled", cls: "bg-sky-50 text-sky-700 border-sky-200" },
  sending: { label: "Sending", cls: "bg-sky-50 text-sky-700 border-sky-200" },
  skipped: { label: "Not sent", cls: "bg-amber-50 text-amber-800 border-amber-200" },
  failed: { label: "Failed", cls: "bg-rose-50 text-rose-700 border-rose-200" },
};

export function formatWhen(iso: string): string {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  const time = d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  return sameDay ? time : `${d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}, ${time}`;
}

/** Visible keyboard focus on every interactive element. */
export const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";

/** 44px tap area on phones; the visual size stays small on desktop. */
export const tapArea = "max-sm:min-h-[44px] max-sm:min-w-[44px]";

export const inputCls =
  `w-full rounded-xl border border-border bg-white px-3 py-2 font-body text-sm text-ink placeholder:text-ink-muted focus:border-primary/50 focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-60 max-sm:min-h-[44px]`;

export const ghostBtn =
  `inline-flex items-center justify-center gap-1.5 rounded-lg border border-border bg-white px-3 py-1.5 font-label text-xs font-semibold text-ink-secondary transition-all hover:border-primary/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40 ${focusRing} ${tapArea}`;

export const primaryBtn =
  `inline-flex items-center justify-center gap-1.5 rounded-full bg-primary px-4 py-2 font-label text-xs font-bold text-white shadow-sm transition-all hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50 ${focusRing} ${tapArea}`;
