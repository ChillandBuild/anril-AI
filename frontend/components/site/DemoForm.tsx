"use client";

import { useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import ui from "./site.module.css";
import { INDUSTRY_OPTIONS, submitDemo, validateDemo, type DemoFields } from "./demo-request";
import s from "./Demo.module.css";

type Status = { kind: "idle" } | { kind: "sending" } | { kind: "sent" } | { kind: "error"; message: string };

const EMPTY: DemoFields = { name: "", phone: "", company: "", industry: "" };
const ORDER: readonly (keyof DemoFields)[] = ["name", "phone", "company", "industry"];

type FieldProps = {
  id: keyof DemoFields;
  label: string;
  value: string;
  error?: string;
  valid: boolean;
  /** Selects always show a value, so their label stays lifted. */
  lifted?: boolean;
  children: (a11y: { id: string; name: string; "aria-invalid": boolean; "aria-describedby"?: string }) => ReactNode;
};

/** A boxed field whose label floats up when the field is focused or filled, with a tick once it is valid. */
function Field({ id, label, value, error, valid, lifted, children }: FieldProps) {
  const inputId = `demo-${id}`;
  const errorId = `${inputId}-err`;
  const cls = [s.field, (lifted || value) && s.filled, valid && s.ok].filter(Boolean).join(" ");
  return (
    <div className={cls}>
      {children({ id: inputId, name: id, "aria-invalid": Boolean(error), "aria-describedby": error ? errorId : undefined })}
      <label htmlFor={inputId}>{label}</label>
      {valid && (
        <svg className={s.tick} viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
          <path d="M4 10.5l4 4 8-9" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {error && <p id={errorId} className={s.fieldError}>{error}</p>}
    </div>
  );
}

/**
 * Demo request. Each field is checked as the visitor leaves it and re-checked as they correct it; the whole
 * form is checked on submit. Shows sending and error states, and ignores repeat submits while one is in flight.
 */
export function DemoForm() {
  const [fields, setFields] = useState<DemoFields>(EMPTY);
  const [touched, setTouched] = useState<Partial<Record<keyof DemoFields, boolean>>>({});
  const [submitted, setSubmitted] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const inFlight = useRef(false);
  const formRef = useRef<HTMLFormElement>(null);
  const doneRef = useRef<HTMLHeadingElement>(null);

  const found = useMemo(() => validateDemo(fields), [fields]);
  const errorOf = (k: keyof DemoFields) => (touched[k] || submitted ? found[k] : undefined);
  const validOf = (k: keyof DemoFields) => Boolean(touched[k]) && !found[k];

  const set = (key: keyof DemoFields) => (e: { target: { value: string } }) => setFields((f) => ({ ...f, [key]: e.target.value }));
  const leave = (key: keyof DemoFields) => () => setTouched((t) => ({ ...t, [key]: true }));

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (inFlight.current) return;
    setSubmitted(true);
    const firstBad = ORDER.find((k) => found[k]);
    if (firstBad) {
      formRef.current?.querySelector<HTMLElement>(`#demo-${firstBad}`)?.focus();
      return;
    }
    inFlight.current = true;
    setStatus({ kind: "sending" });
    const honeypot = (formRef.current?.elements.namedItem("_hp") as HTMLInputElement | null)?.value ?? "";
    const result = await submitDemo(fields, honeypot);
    inFlight.current = false;
    if (result.ok) {
      setStatus({ kind: "sent" });
      requestAnimationFrame(() => doneRef.current?.focus());
    } else {
      setStatus({ kind: "error", message: result.message });
    }
  }

  if (status.kind === "sent") {
    return (
      <div className={s.form} role="status">
        <svg className={s.doneIcon} viewBox="0 0 48 48" width="48" height="48" aria-hidden="true" focusable="false">
          <circle cx="24" cy="24" r="21" fill="none" stroke="currentColor" strokeWidth="2.5" />
          <path d="M14 25l7 7 13-15" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <h3 ref={doneRef} tabIndex={-1} className={s.doneTitle}>Thank you. We have your details.</h3>
        <p className={s.doneText}>We will contact you on {fields.phone.trim()} to set up your demo.</p>
      </div>
    );
  }

  const sending = status.kind === "sending";
  return (
    <form ref={formRef} className={s.form} noValidate onSubmit={onSubmit} aria-busy={sending}>
      <Field id="name" label="Your name" value={fields.name} error={errorOf("name")} valid={validOf("name")}>
        {(a) => <input {...a} autoComplete="name" maxLength={80} value={fields.name} onChange={set("name")} onBlur={leave("name")} />}
      </Field>
      <Field id="phone" label="Phone number" value={fields.phone} error={errorOf("phone")} valid={validOf("phone")}>
        {(a) => <input {...a} type="tel" inputMode="tel" autoComplete="tel" maxLength={20} value={fields.phone} onChange={set("phone")} onBlur={leave("phone")} />}
      </Field>
      <Field id="company" label="Business name" value={fields.company} error={errorOf("company")} valid={validOf("company")}>
        {(a) => <input {...a} autoComplete="organization" maxLength={120} value={fields.company} onChange={set("company")} onBlur={leave("company")} />}
      </Field>
      <Field id="industry" label="Industry" value={fields.industry} error={errorOf("industry")} valid={validOf("industry")} lifted>
        {(a) => (
          <select {...a} value={fields.industry} onChange={set("industry")} onBlur={leave("industry")}>
            <option value="">Choose one</option>
            {INDUSTRY_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        )}
      </Field>
      {/* Bots fill this; people never see it. */}
      <div className={s.hp} aria-hidden="true">
        <label htmlFor="demo-hp">Leave this empty</label>
        <input id="demo-hp" name="_hp" tabIndex={-1} autoComplete="off" />
      </div>
      <button className={`${ui.btn} ${s.submit}`} type="submit" disabled={sending}>
        {sending ? "Sending…" : "Book a demo"}
      </button>
      <p className={s.note} role="alert">{status.kind === "error" ? status.message : ""}</p>
    </form>
  );
}
