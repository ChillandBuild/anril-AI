"use client";

import { useState } from "react";
import {
  Plus,
  Trash2,
  ExternalLink,
  Phone,
  Copy,
  MessageSquare,
  ChevronDown,
  PhoneCall,
} from "lucide-react";
import type { Button } from "../types";
import { Select } from "@/components/ui/Select";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { buttonBlockers, cleanButtonLabel, cleanPhone, fixUrl, groupQuickReplies } from "../template-rules";
import FieldMessages, { SampleInputs, useFixNotes } from "./field-messages";

type ButtonConfig = {
  type: 'QUICK_REPLY' | 'URL' | 'PHONE_NUMBER' | 'WHATSAPP_CALL' | 'COPY_CODE' | 'ONE_TAP';
  text: string;
  url?: string;
  phone?: string;
  country?: string;
  offer_code?: string;
  active_for_days?: number;
  autofill_text?: string;
  package_name?: string;
  signature_hash?: string;
  url_example?: string;
};

type ButtonBuilderProps = {
  buttons: ButtonConfig[];
  onChange: (buttons: ButtonConfig[]) => void;
  maxButtons?: number;
  disableCTA?: boolean;
};

/* ── constants ───────────────────────────────────────────────── */

const BUTTON_TYPES = [
  {
    type: "QUICK_REPLY" as const,
    label: "Quick Reply",
    desc: "Tap-to-reply chip",
    icon: MessageSquare,
    group: "QR",
  },
  {
    type: "URL" as const,
    label: "Visit Website",
    desc: "Opens a URL in the browser",
    icon: ExternalLink,
    group: "CTA",
  },
  {
    type: "PHONE_NUMBER" as const,
    label: "Call Phone Number",
    desc: "Dials a phone number",
    icon: Phone,
    group: "CTA",
  },
  {
    type: "WHATSAPP_CALL" as const,
    label: "Call on WhatsApp",
    desc: "Starts a WhatsApp voice call",
    icon: PhoneCall,
    group: "CTA",
  },
  {
    type: "COPY_CODE" as const,
    label: "Copy Offer Code",
    desc: "Copies a promo code to clipboard",
    icon: Copy,
    group: "CTA",
  },
  {
    type: "ONE_TAP" as const,
    label: "One-Tap Autofill",
    desc: "Autofill OTP button (Android)",
    icon: Copy,
    group: "CTA",
  },
] as const;

const COUNTRY_CODES = [
  { code: "+91", label: "IN +91" },
  { code: "+1", label: "US +1" },
  { code: "+44", label: "UK +44" },
  { code: "+61", label: "AU +61" },
  { code: "+81", label: "JP +81" },
  { code: "+971", label: "AE +971" },
  { code: "+65", label: "SG +65" },
  { code: "+49", label: "DE +49" },
];

/* ── helpers ─────────────────────────────────────────────────── */

function typeLabel(type: string) {
  return BUTTON_TYPES.find((t) => t.type === type)?.label ?? type;
}

function TypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    QUICK_REPLY: "bg-emerald-50 text-emerald-700",
    URL: "bg-blue-50 text-blue-700",
    PHONE_NUMBER: "bg-orange-50 text-orange-700",
    WHATSAPP_CALL: "bg-teal-50 text-teal-700",
    COPY_CODE: "bg-primary-50 text-primary-700",
    ONE_TAP: "bg-pink-50 text-pink-700",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wide ${
        colors[type] ?? "bg-gray-100 text-gray-600"
      }`}
    >
      {typeLabel(type)}
    </span>
  );
}

/* ── component ───────────────────────────────────────────────── */

export default function ButtonBuilder({
  buttons,
  onChange,
  maxButtons = 3,
  disableCTA = false,
}: ButtonBuilderProps) {
  const [showPicker, setShowPicker] = useState(false);

  const availableTypes = disableCTA
    ? BUTTON_TYPES.filter((t) => t.type === "QUICK_REPLY" || t.type === "URL")
    : BUTTON_TYPES;

  const { notes, show, clearAll } = useFixNotes();
  const blockers = buttonBlockers(buttons as Button[]);
  const blockersFor = (fieldId: string) => blockers.filter((b) => b.fieldId === fieldId);

  /** Keeps quick replies side by side (Meta rejects them split by other buttons). */
  function commit(next: ButtonConfig[]) {
    const grouped = groupQuickReplies(next as Button[]);
    if (grouped.note) clearAll(); // per-button notes are keyed by position, which just changed
    show("group", grouped.note);
    onChange(grouped.buttons as ButtonConfig[]);
  }

  function addButton(type: ButtonConfig["type"]) {
    if (buttons.length >= maxButtons) return;
    const newBtn: ButtonConfig = { type, text: "" };
    if (type === "URL") newBtn.url = "";
    if (type === "PHONE_NUMBER" || type === "WHATSAPP_CALL") {
      newBtn.phone = "";
      newBtn.country = "+91";
    }
    if (type === "WHATSAPP_CALL") newBtn.active_for_days = 7;
    if (type === "COPY_CODE") {
      newBtn.text = "Copy offer code";
      newBtn.offer_code = "";
    }
    if (type === "ONE_TAP") {
      newBtn.text = "Autofill";
      newBtn.autofill_text = "Autofill";
      newBtn.package_name = "";
      newBtn.signature_hash = "";
    }
    commit([...buttons, newBtn]);
    setShowPicker(false);
  }

  function update(index: number, field: keyof ButtonConfig, value: string | number) {
    const next = buttons.map((b, i) =>
      i === index ? { ...b, [field]: value } : b,
    );
    onChange(next);
  }

  function remove(index: number) {
    commit(buttons.filter((_, i) => i !== index));
  }

  const urlCount = buttons.filter((b) => b.type === "URL").length;
  const phoneCount = buttons.filter((b) => b.type === "PHONE_NUMBER").length;
  const waCallCount = buttons.filter((b) => b.type === "WHATSAPP_CALL").length;
  const copyCodeCount = buttons.filter((b) => b.type === "COPY_CODE").length;

  const isTypeDisabled = (type: string) => {
    if (type === "URL" && urlCount >= 2) return true;
    if (type === "PHONE_NUMBER" && phoneCount >= 1) return true;
    if (type === "WHATSAPP_CALL" && waCallCount >= 1) return true;
    if (type === "COPY_CODE" && copyCodeCount >= 1) return true;
    return false;
  };


  return (
    <div>
      {/* Section header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <label className="font-body text-sm font-medium text-ink">Buttons</label>
          <span className="inline-flex items-center px-1.5 py-0.5 rounded-md bg-surface-subtle text-[10px] font-semibold text-ink-muted">
            {buttons.length}/{maxButtons}
          </span>
        </div>

        {buttons.length < maxButtons && (
          <button
            type="button"
            onClick={() => setShowPicker(!showPicker)}
            className="flex items-center gap-1 text-sm text-emerald-600 hover:text-emerald-700 font-medium transition-colors"
          >
            <Plus size={15} />
            Add Button
            <ChevronDown
              size={13}
              className={`transition-transform ${showPicker ? "rotate-180" : ""}`}
            />
          </button>
        )}
      </div>

      <FieldMessages id="buttons-messages" note={notes.group} />

      {/* Add-button picker dropdown */}
      {showPicker && buttons.length < maxButtons && (
        <div className="mb-3 p-3 rounded-xl bg-surface-subtle border border-border-subtle animate-slide-up">
          <p className="font-body text-xs text-ink-muted mb-2">
            Select button type:
          </p>
          <div className="grid grid-cols-1 gap-0.5">
            {availableTypes.map((opt) => {
              const Icon = opt.icon;
              const disabled = isTypeDisabled(opt.type);
              return (
                <button
                  key={opt.type}
                  type="button"
                  disabled={disabled}
                  onClick={() => addButton(opt.type)}
                  className={`flex items-center gap-3 p-2.5 rounded-lg transition-all text-left w-full ${
                    disabled
                      ? "opacity-40 cursor-not-allowed bg-gray-50/50"
                      : "hover:bg-white hover:shadow-sm"
                  }`}
                >
                  <div className="w-8 h-8 rounded-lg bg-white border border-border-subtle flex items-center justify-center shrink-0">
                    <Icon size={14} className={disabled ? "text-gray-400" : "text-ink-secondary"} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between">
                      <p className={`font-body text-sm font-medium ${disabled ? "text-gray-400" : "text-ink"}`}>
                        {opt.label}
                      </p>
                      {disabled && (
                        <span className="text-[10px] text-red-500 font-normal bg-red-50 px-1.5 py-0.5 rounded-md border border-red-100">
                          Limit reached
                        </span>
                      )}
                    </div>
                    <p className={`font-body text-[11px] truncate ${disabled ? "text-gray-400/80" : "text-ink-muted"}`}>
                      {opt.desc}
                    </p>
                  </div>
                </button>
              );
            })}
          </div>
          <button
            type="button"
            onClick={() => setShowPicker(false)}
            className="mt-2 text-xs text-ink-muted hover:text-ink-secondary transition-colors"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Empty state */}
      {buttons.length === 0 && !showPicker && (
        <p className="font-body text-xs text-ink-muted">
          Add buttons so users can respond or take action with one tap.
        </p>
      )}

      {/* Button cards */}
      <div className="space-y-3">
        {buttons.map((btn, i) => (
          <div
            key={i}
            className="p-4 rounded-xl bg-white border border-border-subtle shadow-sm space-y-3 animate-slide-up"
          >
            {/* Top row: type badge + delete */}
            <div className="flex items-center justify-between">
              <TypeBadge type={btn.type} />
              <button
                type="button"
                onClick={() => remove(i)}
                className="p-1.5 rounded-lg hover:bg-red-50 text-ink-muted hover:text-red-500 transition-colors"
              >
                <Trash2 size={14} />
              </button>
            </div>

            {/* Button text */}
            <div>
              <p className="font-body text-xs text-ink-muted mb-1">Button label</p>
              {btn.type === "COPY_CODE" ? (
                <div>
                  <input
                    value={btn.text}
                    readOnly
                    className="input text-sm bg-surface-subtle text-ink-muted cursor-not-allowed"
                  />
                  <p className="font-body text-[10px] text-amber-600 mt-1">
                    Meta requires this exact text for Copy Code buttons
                  </p>
                </div>
              ) : (
                <input
                  id={`btn-label-${i}`}
                  value={btn.text}
                  onChange={(e) => {
                    const cleaned = cleanButtonLabel(e.target.value);
                    show(`label-${i}`, cleaned.note);
                    update(i, "text", cleaned.text.slice(0, 25));
                  }}
                  aria-describedby={`btn-label-${i}-messages`}
                  aria-invalid={blockersFor(`btn-label-${i}`).length > 0}
                  placeholder={
                    btn.type === "QUICK_REPLY"
                      ? "e.g. Book Now"
                      : btn.type === "URL"
                        ? "e.g. Visit Website"
                        : "e.g. Call Us"
                  }
                  maxLength={25}
                  className="input text-sm"
                />
              )}
              <FieldMessages
                id={`btn-label-${i}-messages`}
                note={notes[`label-${i}`]}
                blockers={blockersFor(`btn-label-${i}`)}
              />
            </div>

            {/* URL field */}
            {btn.type === "URL" && (
              <div>
                <p className="font-body text-xs text-ink-muted mb-1">
                  Website URL
                </p>
                <input
                  id={`btn-url-${i}`}
                  value={btn.url || ""}
                  onChange={(e) => update(i, "url", e.target.value)}
                  onBlur={(e) => {
                    const fixed = fixUrl(e.target.value);
                    show(`url-${i}`, fixed.note);
                    if (fixed.text !== (btn.url || "")) update(i, "url", fixed.text);
                  }}
                  maxLength={2000}
                  placeholder="https://www.example.com"
                  aria-describedby={`btn-url-${i}-messages`}
                  aria-invalid={blockersFor(`btn-url-${i}`).some((b) => b.inline)}
                  className="input text-sm"
                />
                <FieldMessages
                  id={`btn-url-${i}-messages`}
                  note={notes[`url-${i}`]}
                  blockers={blockersFor(`btn-url-${i}`)}
                />
                {/\{\{\d+\}\}$/.test((btn.url || "").trim()) && (
                  <>
                    <SampleInputs
                      variables={[1]}
                      samples={{ 1: btn.url_example ?? "" }}
                      onChange={(next) => update(i, "url_example", next[1] ?? "")}
                      idPrefix={`btn-urlsample-${i}-`}
                      label="Variable sample"
                      chipLabel={() => "Link {{1}}"}
                    />
                    <FieldMessages
                      id={`btn-urlsample-${i}-messages`}
                      blockers={blockersFor(`btn-urlsample-${i}-1`)}
                    />
                  </>
                )}
              </div>
            )}

            {/* Phone fields */}
            {(btn.type === "PHONE_NUMBER" || btn.type === "WHATSAPP_CALL") && (
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <p className="font-body text-xs text-ink-muted mb-1">Country</p>
                  <Select
                    aria-label="Country code"
                    value={btn.country || "+91"}
                    onChange={(v) => update(i, "country", v)}
                    options={COUNTRY_CODES.map((c) => ({ value: c.code, label: c.label }))}
                  />
                </div>
                <div className="col-span-2">
                  <p className="font-body text-xs text-ink-muted mb-1">
                    Phone number
                  </p>
                  <input
                    id={`btn-phone-${i}`}
                    value={btn.phone || ""}
                    onChange={(e) => update(i, "phone", cleanPhone(e.target.value))}
                    inputMode="numeric"
                    maxLength={15}
                    placeholder="9876543210"
                    className="input text-sm"
                  />
                </div>
              </div>
            )}

            {/* WhatsApp call duration */}
            {btn.type === "WHATSAPP_CALL" && (
              <div>
                <p className="font-body text-xs text-ink-muted mb-1">Active for</p>
                <SegmentedControl
                  aria-label="Active for"
                  value={String(btn.active_for_days || 7)}
                  onChange={(v) => update(i, "active_for_days", parseInt(v))}
                  options={[
                    { value: "7", label: "7 days" },
                    { value: "30", label: "30 days" },
                    { value: "90", label: "90 days" },
                  ]}
                />
              </div>
            )}

            {/* Offer code */}
            {btn.type === "COPY_CODE" && (
              <div>
                <p className="font-body text-xs text-ink-muted mb-1">
                  Offer code
                </p>
                <input
                  value={btn.offer_code || ""}
                  onChange={(e) =>
                    update(i, "offer_code", e.target.value.slice(0, 20))
                  }
                  placeholder="e.g. SAVE20"
                  maxLength={20}
                  className="input text-sm"
                />
              </div>
            )}

            {/* ONE TAP / Autofill Fields */}
            {btn.type === "ONE_TAP" && (
              <div className="space-y-3 border-t border-border-subtle pt-3">
                <div>
                  <p className="font-body text-xs text-ink-muted mb-1">
                    Autofill Button Text
                  </p>
                  <input
                    value={btn.autofill_text || "Autofill"}
                    onChange={(e) => update(i, "autofill_text", e.target.value.slice(0, 25))}
                    placeholder="e.g. Autofill"
                    maxLength={25}
                    className="input text-sm"
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <p className="font-body text-xs text-ink-muted mb-1">
                      Android Package Name
                    </p>
                    <input
                      value={btn.package_name || ""}
                      onChange={(e) => update(i, "package_name", e.target.value)}
                      placeholder="e.g. com.company.app"
                      className="input text-sm"
                    />
                  </div>
                  <div>
                    <p className="font-body text-xs text-ink-muted mb-1">
                      App Signature Hash
                    </p>
                    <input
                      value={btn.signature_hash || ""}
                      onChange={(e) => update(i, "signature_hash", e.target.value)}
                      placeholder="e.g. ab12cd34ef..."
                      className="input text-sm"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
