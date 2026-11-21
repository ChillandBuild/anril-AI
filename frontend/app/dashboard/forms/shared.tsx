"use client";
import { useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, MoreVertical, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  WaFormField,
  WaFormFieldType,
  WaFormKind,
  WaFormSettings,
  WaFormLanguage,
  WaFormSetup,
  WaFormVersionStatus,
} from "@/lib/api";

/* Dashboard wording for the builder. The words customers see are never here: they come from the
 * client's own texts (backend services/form_texts.py), in English, Tamil or Tanglish. */

export const FIELD_TYPE_LABELS: Record<WaFormFieldType, string> = {
  text: "Short answer",
  long_text: "Long answer",
  email: "Email",
  phone: "Phone number",
  number: "Number",
  date: "Date",
  dropdown: "Dropdown",
  single: "One choice",
  multi: "Several choices",
};

export const CHOICE_TYPES: WaFormFieldType[] = ["dropdown", "single", "multi"];

/** Friendly names for each editable text, and where it shows. */
export const TEXT_LABELS: Record<string, { label: string; hint: string; multiline?: boolean }> = {
  cta: { label: "Button that opens the form", hint: "Under the chat message" },
  form_cta: { label: "Button that opens the form", hint: "Under the chat message" },
  intro: { label: "Message sent with the form", hint: "The chat message the button sits under", multiline: true },
  title_choose: { label: "First screen title", hint: "Where they pick a package" },
  choose_label: { label: "Package question", hint: "Above the package list" },
  title_option: { label: "Option screen title", hint: "Sub-packages, when a package has them" },
  title_addons: { label: "Add-ons screen title", hint: "When the choice has add-ons" },
  addons_label: { label: "Add-ons question", hint: "Above the add-on list" },
  title_details: { label: "Questions screen title", hint: "Every screen with questions" },
  title_confirm: { label: "Last screen title", hint: "Where they press the submit button" },
  continue: { label: "Next button", hint: "Bottom of each screen" },
  submit: { label: "Submit button", hint: "Bottom of the last screen" },
  confirm_note: { label: "Last screen text", hint: "Above the submit button", multiline: true },
  form_note: { label: "Last screen text", hint: "Above the submit button", multiline: true },
  consent: { label: "Offers opt-in", hint: "Optional tick box. Starts unticked" },
  total: { label: "“Total” word", hint: "In the payment message" },
  incl_gst: { label: "“incl. GST” words", hint: "In the payment message" },
  pay_note: { label: "Payment message line", hint: "Above the pay button", multiline: true },
  pay_button: { label: "Pay button", hint: "{amount} becomes the total, e.g. ₹1,198" },
  thank_you: { label: "Thank-you message", hint: "Sent in the chat after they submit", multiline: true },
  // live order form
  title_search: { label: "Search screen title", hint: "Where they type what they want" },
  search_label: { label: "Search box", hint: "Inside the search box" },
  no_results: { label: "Nothing found", hint: "When the search finds no product" },
  title_products: { label: "Products screen title", hint: "Where they tick products" },
  products_label: { label: "Products question", hint: "Above your Catalogue items" },
  title_quantity: { label: "Quantity screen title", hint: "Where they pick how many" },
  title_delivery: { label: "Delivery screen title", hint: "Where they type name and address" },
  name_label: { label: "Name box", hint: "On the delivery screen" },
  address_label: { label: "Address box", hint: "On the delivery screen" },
  title_summary: { label: "Summary screen title", hint: "The order and total, before they submit" },
  summary_note: { label: "Summary text", hint: "Under the order and total", multiline: true },
  // live booking form
  title_date: { label: "Date screen title", hint: "Where they pick a day" },
  date_label: { label: "Date question", hint: "Above the free days" },
  no_slots: { label: "No free days", hint: "When every day is full" },
  title_slot: { label: "Time screen title", hint: "Where they pick a time" },
  slot_label: { label: "Time question", hint: "Above the free times" },
  title_full: { label: "Fully booked screen title", hint: "When nothing is free" },
  full_note: { label: "Fully booked text", hint: "Shown when nothing is free", multiline: true },
  booked_message: { label: "Booking confirmed message", hint: "Sent in the chat. {slot} becomes the day and time", multiline: true },
  slot_taken: { label: "Time just taken message", hint: "Sent if someone booked that time first", multiline: true },
};

export const SERVICES_TEXT_KEYS = [
  "cta", "title_choose", "choose_label", "title_option", "title_addons", "addons_label", "title_details",
  "title_confirm", "continue", "submit", "confirm_note", "consent", "total", "incl_gst", "pay_note", "pay_button",
];
export const CUSTOM_TEXT_KEYS = [
  "intro", "form_cta", "title_details", "title_confirm", "continue", "submit", "form_note", "consent", "thank_you",
];
export const ORDER_TEXT_KEYS = [
  "intro", "form_cta", "title_search", "search_label", "no_results", "title_products", "products_label",
  "title_quantity", "title_delivery", "name_label", "address_label", "title_summary", "summary_note",
  "continue", "submit", "consent",
];
export const BOOKING_TEXT_KEYS = [
  "intro", "form_cta", "title_date", "date_label", "no_slots", "title_slot", "slot_label", "title_details",
  "title_confirm", "form_note", "title_full", "full_note", "continue", "submit", "consent", "booked_message", "slot_taken",
];

/** The words a form of this kind shows. */
export function textKeysFor(kind: WaFormKind): string[] {
  return kind === "order" ? ORDER_TEXT_KEYS : kind === "booking" ? BOOKING_TEXT_KEYS : CUSTOM_TEXT_KEYS;
}

export const KIND_NAMES: Record<WaFormKind, string> = {
  standard: "Questions",
  order: "Product order",
  booking: "Appointment booking",
};

export function effectiveText(setup: WaFormSetup, language: WaFormLanguage, texts: Record<string, string>, key: string) {
  const own = texts[key];
  return own && own.trim() ? own : setup.texts[language]?.[key] ?? "";
}

/** Shown length of a text: the pay button with the longest amount filled in, as the backend checks. */
export function shownLength(key: string, value: string) {
  return (key === "pay_button" ? value.replace("{amount}", "₹99,99,999") : value).length;
}

/* ── status ─────────────────────────────────────────────────────────────────── */

export function StatusChip({ status, live, className }: { status: WaFormVersionStatus; live: boolean; className?: string }) {
  const look =
    status.state === "publishing"
      ? { text: "Publishing…", cls: "bg-blue-50 text-blue-700", dot: "bg-blue-500 animate-pulse" }
      : status.state === "failed"
        ? { text: "Not published", cls: "bg-amber-50 text-amber-800", dot: "bg-amber-500" }
        : live
          ? { text: "Live on WhatsApp", cls: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" }
          : status.live
            ? { text: "Changes not published", cls: "bg-amber-50 text-amber-800", dot: "bg-amber-500" }
            : { text: "Draft", cls: "bg-surface-mid text-ink-secondary", dot: "bg-ink-muted" };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-label text-[11px] font-semibold",
        look.cls,
        className,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", look.dot)} aria-hidden />
      {look.text}
    </span>
  );
}

export const LANGUAGE_CHIP: Record<WaFormLanguage, string> = { en: "English", ta: "தமிழ்", tanglish: "Tanglish" };

/* ── editable texts ─────────────────────────────────────────────────────────── */

/**
 * Every text the form shows, filled with the language's starting words. Editing a box saves only
 * that edit; clearing it (or Reset) goes back to the language's words, so switching language
 * re-fills everything you didn't change.
 */
export function FormTextsEditor({
  setup, language, texts, keys, onChange, disabled,
}: {
  setup: WaFormSetup;
  language: WaFormLanguage;
  texts: Record<string, string>;
  keys: string[];
  onChange: (texts: Record<string, string>) => void;
  disabled?: boolean;
}) {
  function set(key: string, value: string) {
    const next = { ...texts };
    const preset = setup.texts[language]?.[key] ?? "";
    if (!value.trim() || value === preset) delete next[key];
    else next[key] = value;
    onChange(next);
  }
  return (
    <div className="divide-y divide-surface-mid rounded-xl ring-1 ring-surface-mid">
      {keys.map((key) => {
        const meta = TEXT_LABELS[key] ?? { label: key, hint: "" };
        const value = effectiveText(setup, language, texts, key);
        const limit = setup.text_limits[key] ?? 1000;
        const length = shownLength(key, value);
        const edited = Boolean(texts[key]?.trim());
        const InputTag = meta.multiline ? "textarea" : "input";
        return (
          <div key={key} className="grid gap-1.5 bg-surface px-3 py-3 first:rounded-t-xl last:rounded-b-xl sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)] sm:gap-4">
            <div className="min-w-0">
              <p className="font-label text-xs font-semibold text-ink">{meta.label}</p>
              <p className="font-body text-[11px] leading-snug text-ink-muted">{meta.hint}</p>
            </div>
            <div className="min-w-0 space-y-1">
              <InputTag
                aria-label={meta.label}
                value={value}
                rows={meta.multiline ? 2 : undefined}
                disabled={disabled}
                onChange={(e: React.ChangeEvent<HTMLInputElement & HTMLTextAreaElement>) => set(key, e.target.value)}
                className={cn(
                  "w-full rounded-lg border bg-surface-low px-3 py-1.5 font-body text-sm text-ink focus:bg-white focus:outline-none",
                  length > limit ? "border-red-300 focus:border-red-400" : "border-transparent focus:border-primary/40",
                  meta.multiline && "resize-y leading-relaxed",
                )}
              />
              <div className="flex items-center justify-between gap-2">
                <span className={cn("font-body text-[11px] tabular-nums", length > limit ? "font-semibold text-red-600" : "text-ink-muted")}>
                  {length}/{limit}
                </span>
                {edited && !disabled && (
                  <button
                    type="button"
                    onClick={() => set(key, "")}
                    className="font-label text-[11px] font-semibold text-primary-600 hover:text-primary-700"
                  >
                    Reset to {LANGUAGE_CHIP[language]}
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── phone preview ──────────────────────────────────────────────────────────── */

const FIELDS_PER_SCREEN = 5; // backend whatsapp_forms.FIELDS_PER_SCREEN

function MockInput({ field }: { field: WaFormField }) {
  const label = field.label.trim() || "Question";
  const options = field.options.filter((o) => o.trim());
  if (field.type === "single" || field.type === "multi") {
    return (
      <div className="space-y-1.5">
        <p className="text-[12px] font-semibold text-[#111b21]">
          {label}
          {!field.required && <span className="font-normal text-[#667781]"> (optional)</span>}
        </p>
        {(options.length ? options : ["Option"]).slice(0, 6).map((o, i) => (
          <div key={i} className="flex items-center justify-between rounded-lg border border-[#e9edef] px-2.5 py-1.5">
            <span className="truncate text-[12px] text-[#111b21]">{o}</span>
            <span className={cn("h-3.5 w-3.5 shrink-0 border-[1.5px] border-[#8696a0]", field.type === "single" ? "rounded-full" : "rounded")} />
          </div>
        ))}
      </div>
    );
  }
  const hint =
    field.type === "date" ? "📅" : field.type === "dropdown" ? "▾" : field.type === "long_text" ? "" : "";
  return (
    <div className={cn("rounded-lg border border-[#c4cdd2] px-2.5 pb-1.5 pt-1", field.type === "long_text" && "pb-6")}>
      <p className="text-[10px] text-[#667781]">
        {label}
        {!field.required && " (optional)"}
      </p>
      <p className="flex items-center justify-between text-[12px] text-[#8696a0]">
        <span>&nbsp;</span>
        <span>{hint}</span>
      </p>
    </div>
  );
}

interface PhonePage {
  /** Under the phone, e.g. "Screen 2 of 3". */
  caption: string;
  title: string;
  body: ReactNode;
  button: string;
}

/** A WhatsApp-style phone: the chat message with its button first, then each form screen. */
function PhonePager({ words, pages }: { words: Record<string, string>; pages: PhonePage[] }) {
  const total = pages.length + 1;
  const [page, setPage] = useState(0);
  const current = Math.min(page, total - 1);
  const screen = current > 0 ? pages[current - 1] : null;

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative w-[272px] overflow-hidden rounded-[2.2rem] border-[7px] border-[#0A1528] bg-[#efeae2] shadow-xl">
        <div className="flex items-center gap-2 bg-[#008069] px-3 pb-2 pt-3 text-white">
          <div className="h-6 w-6 rounded-full bg-white/30" />
          <p className="text-[12px] font-semibold">Your business</p>
        </div>
        <div className="flex h-[460px] flex-col">
          {!screen ? (
            <div className="flex flex-1 flex-col justify-end p-3">
              <div className="max-w-[88%] rounded-lg rounded-tl-none bg-white px-2.5 py-2 text-[12px] leading-snug text-[#111b21] shadow-sm">
                <p className="whitespace-pre-line">{words.intro || "…"}</p>
                <div className="mt-2 border-t border-[#e9edef] pt-1.5 text-center text-[12px] font-semibold text-[#008069]">
                  📝 {words.form_cta || "…"}
                </div>
              </div>
            </div>
          ) : (
            <div className="mt-6 flex flex-1 flex-col rounded-t-2xl bg-white">
              <div className="flex items-center justify-between border-b border-[#e9edef] px-3 py-2.5">
                <X size={14} className="text-[#54656f]" />
                <p className="truncate px-2 text-[13px] font-semibold text-[#111b21]">{screen.title}</p>
                <MoreVertical size={14} className="text-[#54656f]" />
              </div>
              <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3">{screen.body}</div>
              <div className="px-3 pb-3">
                <div className="rounded-full bg-[#008069] py-2 text-center text-[12px] font-semibold text-white">{screen.button}</div>
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          aria-label="Previous screen"
          onClick={() => setPage(Math.max(0, current - 1))}
          disabled={current === 0}
          className="rounded-full p-1.5 text-ink-secondary hover:bg-surface-mid disabled:opacity-30"
        >
          <ChevronLeft size={16} />
        </button>
        <span className="font-label text-xs text-ink-muted tabular-nums">{screen ? screen.caption : "Chat message"}</span>
        <button
          type="button"
          aria-label="Next screen"
          onClick={() => setPage(Math.min(total - 1, current + 1))}
          disabled={current === total - 1}
          className="rounded-full p-1.5 text-ink-secondary hover:bg-surface-mid disabled:opacity-30"
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}

function ConsentBox({ text }: { text: string }) {
  return (
    <label className="flex items-start gap-2 text-[11px] leading-snug text-[#111b21]">
      <span className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded border-[1.5px] border-[#8696a0]" />
      {text}
    </label>
  );
}

function MockChoices({ label, items, multi }: { label: string; items: string[]; multi?: boolean }) {
  return (
    <div className="space-y-1.5">
      <p className="text-[12px] font-semibold text-[#111b21]">{label}</p>
      {items.map((item) => (
        <div key={item} className="flex items-center justify-between gap-2 rounded-lg border border-[#e9edef] px-2.5 py-2 text-[12px] text-[#111b21]">
          <span className="min-w-0 truncate">{item}</span>
          <span className={cn("h-3.5 w-3.5 shrink-0 border-[1.5px] border-[#8696a0]", multi ? "rounded" : "rounded-full")} />
        </div>
      ))}
    </div>
  );
}

function MockBox({ label }: { label: string }) {
  return (
    <div className="rounded-lg border border-[#8696a0] px-2.5 pb-2 pt-1">
      <p className="text-[10px] text-[#667781]">{label}</p>
      <p className="h-4" />
    </div>
  );
}

function questionChunks(fields: WaFormField[], atLeastOne: boolean): WaFormField[][] {
  const chunks: WaFormField[][] = [];
  for (let i = 0; i < Math.max(fields.length, atLeastOne ? 1 : 0); i += FIELDS_PER_SCREEN) chunks.push(fields.slice(i, i + FIELDS_PER_SCREEN));
  return chunks;
}

/**
 * A WhatsApp-style preview: the chat message with its button, then each screen of the form, in the
 * form's own words. Screens split the same way the backend builds them.
 */
export function FormPhonePreview({
  fields, words,
}: {
  fields: WaFormField[];
  /** The texts the form will show (already resolved for its language and edits). */
  words: Record<string, string>;
}) {
  const chunks = questionChunks(fields, true);
  const pages: PhonePage[] = chunks.map((chunk, i) => ({
    caption: `Screen ${i + 1} of ${chunks.length}`,
    title: words.title_details,
    button: words.continue,
    body: fields.length === 0
      ? <p className="text-[12px] text-[#667781]">Add a question to see it here.</p>
      : chunk.map((f, j) => <MockInput key={`${f.key}-${j}`} field={f} />),
  }));
  pages.push({
    caption: "Last screen",
    title: words.title_confirm,
    button: words.submit,
    body: (
      <>
        <p className="whitespace-pre-line text-[12px] leading-snug text-[#111b21]">{words.form_note}</p>
        <ConsentBox text={words.consent} />
      </>
    ),
  });
  return <PhonePager words={words} pages={pages} />;
}

/**
 * Preview of a live form. The products and times are examples: on WhatsApp they come from the
 * Catalogue and the booking hours at the moment the customer opens the form.
 */
export function LiveFormPhonePreview({
  kind, settings, fields, words,
}: {
  kind: "order" | "booking";
  settings: WaFormSettings;
  fields: WaFormField[];
  words: Record<string, string>;
}) {
  const example = (
    <p className="rounded-md bg-[#f0f2f5] px-2 py-1 text-[10px] text-[#667781]">
      Example. Customers see your real {kind === "order" ? "Catalogue items, prices and stock" : "free times"}.
    </p>
  );
  const pages: PhonePage[] = [];
  if (kind === "order") {
    pages.push(
      { caption: "Search", title: words.title_search, button: words.continue, body: <MockBox label={words.search_label} /> },
      {
        caption: "Products", title: words.title_products, button: words.continue,
        body: <>{example}<MockChoices multi label={words.products_label} items={["Product 1 · ₹250", "Product 2 · ₹400", "Product 3 · ₹120"]} /></>,
      },
      {
        caption: "Quantity", title: words.title_quantity, button: words.continue,
        body: <>{example}<MockBox label="Product 1" /><MockBox label="Product 2" /></>,
      },
    );
    if (settings.ask_address) {
      pages.push({
        caption: "Delivery", title: words.title_delivery, button: words.continue,
        body: <><MockBox label={words.name_label} /><MockBox label={words.address_label} /></>,
      });
    }
    pages.push({
      caption: "Summary", title: words.title_summary, button: words.submit,
      body: (
        <>
          {example}
          <p className="whitespace-pre-line rounded-lg bg-[#f0f2f5] px-2.5 py-2 text-[12px] leading-snug text-[#111b21]">
            {"2 × Product 1 · ₹500\n1 × Product 2 · ₹400\nTotal: ₹900"}
          </p>
          <p className="whitespace-pre-line text-[12px] leading-snug text-[#111b21]">{words.summary_note}</p>
          <ConsentBox text={words.consent} />
        </>
      ),
    });
  } else {
    pages.push(
      {
        caption: "Day", title: words.title_date, button: words.continue,
        body: <>{example}<MockChoices label={words.date_label} items={["Mon, 23 Nov", "Tue, 24 Nov", "Thu, 26 Nov"]} /></>,
      },
      {
        caption: "Time", title: words.title_slot, button: words.continue,
        body: <>{example}<MockChoices label={words.slot_label} items={["10:00 am", "10:30 am", "11:00 am"]} /></>,
      },
    );
    const chunks = questionChunks(fields, false);
    chunks.forEach((chunk, i) => pages.push({
      caption: `Questions ${i + 1} of ${chunks.length}`, title: words.title_details, button: words.continue,
      body: chunk.map((f, j) => <MockInput key={`${f.key}-${j}`} field={f} />),
    }));
    pages.push({
      caption: "Last screen", title: words.title_confirm, button: words.submit,
      body: (
        <>
          <p className="rounded-lg bg-[#f0f2f5] px-2.5 py-2 text-[12px] font-semibold text-[#111b21]">Mon, 23 Nov · 10:30 am</p>
          <p className="whitespace-pre-line text-[12px] leading-snug text-[#111b21]">{words.form_note}</p>
          <ConsentBox text={words.consent} />
        </>
      ),
    });
  }
  return <PhonePager words={words} pages={pages} />;
}
