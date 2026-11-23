"use client";

import { useRef } from "react";
import { ImagePlus, Trash2 } from "lucide-react";
import { SwitchPill } from "@/components/ui/controls";
import type { BrandImageKind, BusinessDetails, GstType } from "@/lib/businessDetailsApi";
import { cleanPrefix, financialYear, previewBillNumber, stateCodeOf } from "./taxSplit";
import type { FieldErrors } from "./validate";


export type BusinessDetailsGroup = "name" | "contact" | "tax" | "paid" | "terms";

/** The five cards of the Business details page, in order, each with its one-line hint. */
export const BUSINESS_DETAILS_GROUPS: { id: BusinessDetailsGroup; title: string; hint: string }[] = [
  { id: "name", title: "Name and address", hint: "Who the bill is from" },
  { id: "contact", title: "Contact and logo", hint: "How customers reach you" },
  { id: "tax", title: "Tax and GST", hint: "How GST and bill numbers show on bills" },
  { id: "paid", title: "Getting paid", hint: "Printed so customers can pay you" },
  { id: "terms", title: "Terms and signature", hint: "The fine print at the bottom" },
];

type Props = {
  /** Which card's fields to draw. */
  group: BusinessDetailsGroup;
  draft: BusinessDetails;
  onChange: (patch: Partial<BusinessDetails>) => void;
  errors: FieldErrors;
  canManage: boolean;
  logoUrl?: string | null;
  signatureUrl?: string | null;
  busyImage: BrandImageKind | null;
  onPickImage: (kind: BrandImageKind, file: File) => void;
  onRemoveImage: (kind: BrandImageKind) => void;
};

const INPUT =
  "w-full rounded-xl border border-border bg-white px-3 py-2.5 font-body text-sm text-ink outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:cursor-not-allowed disabled:opacity-60";
const LABEL = "mb-1.5 block font-label text-xs font-bold uppercase tracking-wider text-ink-secondary";
const HINT = "mt-1 text-xs text-ink-secondary";

const GST_OPTIONS: { value: GstType; label: string; hint: string }[] = [
  { value: "regular", label: "Registered", hint: "You collect GST and give a tax invoice." },
  { value: "composition", label: "Composition", hint: "No tax on the bill. It says “Bill of supply”." },
  { value: "none", label: "Not registered", hint: "A simple bill with no GST." },
];

function Field({
  label,
  error,
  hint,
  className,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={className}>
      <span className={LABEL}>{label}</span>
      {children}
      {error ? <p data-field-error className="mt-1 text-xs text-danger">{error}</p> : hint ? <p className={HINT}>{hint}</p> : null}
    </label>
  );
}

function PictureField({
  kind,
  label,
  hint,
  url,
  busy,
  disabled,
  onPick,
  onRemove,
}: {
  kind: BrandImageKind;
  label: string;
  hint: string;
  url?: string | null;
  busy: boolean;
  disabled: boolean;
  onPick: (kind: BrandImageKind, file: File) => void;
  onRemove: (kind: BrandImageKind) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div>
      <span className={LABEL}>{label}</span>
      <div className="flex items-center gap-3 rounded-xl border border-border bg-white p-3">
        <div className="flex h-14 w-20 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border-subtle bg-surface-low">
          {url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url} alt={label} className="max-h-full max-w-full object-contain" />
          ) : (
            <ImagePlus size={20} className="text-ink-secondary" aria-hidden />
          )}
        </div>
        <div className="flex min-w-0 flex-wrap gap-2">
          <button
            type="button"
            disabled={disabled || busy}
            onClick={() => input.current?.click()}
            className="min-h-[40px] rounded-lg border border-border px-3 font-label text-xs font-semibold text-ink transition hover:bg-surface-low disabled:opacity-60"
          >
            {busy ? "Saving…" : url ? "Change picture" : "Add picture"}
          </button>
          {url && (
            <button
              type="button"
              disabled={disabled || busy}
              onClick={() => onRemove(kind)}
              className="inline-flex min-h-[40px] items-center gap-1 rounded-lg px-3 font-label text-xs font-semibold text-danger transition hover:bg-red-50 disabled:opacity-60"
            >
              <Trash2 size={14} aria-hidden /> Remove
            </button>
          )}
        </div>
        <input
          ref={input}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) onPick(kind, file);
          }}
        />
      </div>
      <p className={HINT}>{hint}</p>
    </div>
  );
}

export function BusinessDetailsFields({
  group,
  draft,
  onChange,
  errors,
  canManage,
  logoUrl,
  signatureUrl,
  busyImage,
  onPickImage,
  onRemoveImage,
}: Props) {
  const off = !canManage;
  const derivedState = stateCodeOf("", draft.gstin);
  const sample = previewBillNumber(draft.bill_prefix, financialYear(new Date()), 1);

  return (
    <>
      {group === "name" && (
        <div className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Legal business name" className="sm:col-span-2">
            <input
              className={INPUT}
              value={draft.legal_name}
              disabled={off}
              placeholder="e.g. Anril Bakes Pvt Ltd"
              onChange={(e) => onChange({ legal_name: e.target.value })}
            />
          </Field>
          <Field label="Name on bills" hint="Leave blank to use the legal name." className="sm:col-span-2">
            <input
              className={INPUT}
              value={draft.bill_name}
              disabled={off}
              placeholder="e.g. Anril Bakes"
              onChange={(e) => onChange({ bill_name: e.target.value })}
            />
          </Field>
          <Field label="Address" className="sm:col-span-2">
            <input
              className={INPUT}
              value={draft.address}
              disabled={off}
              placeholder="Street, area"
              onChange={(e) => onChange({ address: e.target.value })}
            />
          </Field>
          <Field label="City">
            <input className={INPUT} value={draft.city} disabled={off} placeholder="e.g. Coimbatore" onChange={(e) => onChange({ city: e.target.value })} />
          </Field>
          <Field label="Pincode">
            <input className={INPUT} value={draft.pincode} disabled={off} placeholder="e.g. 641001" onChange={(e) => onChange({ pincode: e.target.value })} />
          </Field>
          <Field label="State">
            <input className={INPUT} value={draft.state} disabled={off} placeholder="e.g. Tamil Nadu" onChange={(e) => onChange({ state: e.target.value })} />
          </Field>
          <Field
            label="State code"
            error={errors.state_code}
            hint={derivedState && !draft.state_code ? `From your GSTIN: ${derivedState}` : "Two digits, like 33 for Tamil Nadu."}
          >
            <input
              className={INPUT}
              value={draft.state_code}
              disabled={off}
              inputMode="numeric"
              maxLength={2}
              placeholder={derivedState || "33"}
              onChange={(e) => onChange({ state_code: e.target.value.replace(/\D/g, "") })}
            />
          </Field>
        </div>
      </div>
      )}

      {group === "contact" && (
        <div className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Email">
            <input className={INPUT} value={draft.email} disabled={off} placeholder="billing@yourbusiness.com" onChange={(e) => onChange({ email: e.target.value })} />
          </Field>
          <Field label="Phone">
            <input className={INPUT} value={draft.phone} disabled={off} placeholder="e.g. 9876543210" onChange={(e) => onChange({ phone: e.target.value })} />
          </Field>
          <PictureField
            kind="logo"
            label="Logo"
            hint="PNG, JPG or WEBP, under 1 MB. Shown at the top of the bill."
            url={logoUrl}
            busy={busyImage === "logo"}
            disabled={off}
            onPick={onPickImage}
            onRemove={onRemoveImage}
          />
        </div>
      </div>
      )}

      {group === "tax" && (
        <div className="space-y-4">
        <div role="radiogroup" aria-label="GST type" className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {GST_OPTIONS.map((o) => {
            const on = draft.gst_type === o.value;
            return (
              <button
                key={o.value}
                type="button"
                role="radio"
                aria-checked={on}
                disabled={off}
                onClick={() => onChange({ gst_type: o.value })}
                className={`rounded-xl border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-60 ${
                  on ? "border-primary bg-primary/5 ring-2 ring-primary/15" : "border-border bg-white hover:bg-surface-low"
                }`}
              >
                <span className="block font-label text-sm font-semibold text-ink">{o.label}</span>
                <span className="mt-0.5 block text-xs text-ink-secondary">{o.hint}</span>
              </button>
            );
          })}
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="GSTIN" error={errors.gstin} hint="Leave blank if you're not GST-registered.">
            <input
              className={`${INPUT} font-mono uppercase tracking-wide`}
              value={draft.gstin}
              disabled={off}
              maxLength={15}
              placeholder="e.g. 33AAAAA0000A1Z5"
              onChange={(e) => onChange({ gstin: e.target.value.toUpperCase() })}
            />
          </Field>
          <Field label="PAN" error={errors.pan}>
            <input
              className={`${INPUT} font-mono uppercase tracking-wide`}
              value={draft.pan}
              disabled={off}
              maxLength={10}
              placeholder="e.g. ABCDE1234F"
              onChange={(e) => onChange({ pan: e.target.value.toUpperCase() })}
            />
          </Field>
          <Field label="Licence number" hint="For example a food or drug licence. Printed on the bill.">
            <input
              className={INPUT}
              value={draft.licence_number}
              disabled={off}
              maxLength={60}
              onChange={(e) => onChange({ licence_number: e.target.value })}
            />
          </Field>
        </div>
        <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-surface-low p-4">
          <div>
            <p className="font-label text-sm font-semibold text-ink">My prices include GST</p>
            <p className="mt-1 max-w-md font-body text-xs leading-relaxed text-ink-secondary">
              {draft.prices_include_gst
                ? "On: a ₹499 price is what the customer pays (tax is inside)."
                : "Off: GST is added on top at checkout."}
            </p>
          </div>
          <SwitchPill
            on={draft.prices_include_gst}
            disabled={off}
            onChange={(next) => onChange({ prices_include_gst: next })}
            aria-label="Prices include GST"
          />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            label="Bill prefix"
            hint={`Optional, like DS. Your next bill reads ${sample}. The count starts again every April.`}
          >
            <input
              className={`${INPUT} font-mono uppercase`}
              value={draft.bill_prefix}
              disabled={off}
              maxLength={6}
              placeholder="e.g. DS"
              onChange={(e) => onChange({ bill_prefix: cleanPrefix(e.target.value) })}
            />
          </Field>
        </div>
        <p className={HINT}>Bills you have already given keep their old numbers. Refund notes (CN) keep their own numbers.</p>
      </div>
      )}

      {group === "paid" && (
        <div className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="UPI ID" error={errors.upi_id} hint="Printed on the bill so customers can pay.">
            <input
              className={INPUT}
              value={draft.upi_id}
              disabled={off}
              placeholder="e.g. shopname@okbank"
              autoCapitalize="none"
              onChange={(e) => onChange({ upi_id: e.target.value.trim() })}
            />
          </Field>
          <Field label="Account name">
            <input className={INPUT} value={draft.bank_account_name} disabled={off} onChange={(e) => onChange({ bank_account_name: e.target.value })} />
          </Field>
          <Field label="Bank name">
            <input className={INPUT} value={draft.bank_name} disabled={off} onChange={(e) => onChange({ bank_name: e.target.value })} />
          </Field>
          <Field label="IFSC" error={errors.bank_ifsc}>
            <input
              className={`${INPUT} font-mono uppercase`}
              value={draft.bank_ifsc}
              disabled={off}
              maxLength={11}
              placeholder="e.g. SBIN0001234"
              onChange={(e) => onChange({ bank_ifsc: e.target.value.toUpperCase() })}
            />
          </Field>
          <Field
            label="Account number"
            error={errors.bank_account_number}
            hint={off ? "Only the last 4 digits are shown to you." : "The bill shows only the last 4 digits."}
          >
            <input
              className={`${INPUT} font-mono`}
              value={draft.bank_account_number}
              disabled={off}
              inputMode="numeric"
              autoComplete="off"
              onChange={(e) => onChange({ bank_account_number: e.target.value.replace(/\s/g, "") })}
            />
          </Field>
        </div>
      </div>
      )}

      {group === "terms" && (
        <div className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label={`Terms (${draft.terms.length}/1000)`} className="sm:col-span-2">
            <textarea
              className={`${INPUT} min-h-[96px]`}
              value={draft.terms}
              disabled={off}
              maxLength={1000}
              placeholder="e.g. Goods once sold can be exchanged within 7 days with the bill."
              onChange={(e) => onChange({ terms: e.target.value })}
            />
          </Field>
          <PictureField
            kind="signature"
            label="Signature"
            hint="PNG, JPG or WEBP, under 1 MB. Shown at the bottom of the bill."
            url={signatureUrl}
            busy={busyImage === "signature"}
            disabled={off}
            onPick={onPickImage}
            onRemove={onRemoveImage}
          />
        </div>
      </div>
      )}
    </>
  );
}
