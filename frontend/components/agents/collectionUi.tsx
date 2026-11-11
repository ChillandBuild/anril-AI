"use client";
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { BTN_DANGER, BTN_PRIMARY, BTN_SECONDARY, Field, INPUT } from "./ui";
import { KbDialog } from "./KbDialog";
import { nameProblem, nextTabIndex } from "./collectionRows";
import type { KbDocState } from "./knowledgeRows";

/** Small shared pieces of the Collections pages: tabs, polling, dialogs, state pill. */

/** A smaller secondary button for row actions. */
export const BTN_ROW = `${BTN_SECONDARY} !min-h-8 !px-3 text-[13px]`;

const errorText = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);
export { errorText };

/**
 * Runs `tick` every `ms` while `enabled`. Waits for each run to finish before scheduling
 * the next, does nothing while the browser tab is hidden (and runs once as soon as it is
 * visible again), and clears everything on unmount or when `enabled` turns false.
 */
export function usePolling(tick: () => Promise<unknown> | void, enabled: boolean, ms = 3000) {
  const tickRef = useRef(tick);
  tickRef.current = tick;
  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let running = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      if (stopped || document.hidden) return;
      if (timer !== undefined) clearTimeout(timer);
      timer = setTimeout(run, ms);
    };
    const run = async () => {
      if (running) return;
      running = true;
      timer = undefined;
      try {
        await tickRef.current();
      } catch {
        // a failed refresh keeps what is on screen; the next tick tries again
      }
      running = false;
      schedule();
    };
    const onVisibility = () => {
      // While a run is in flight it schedules the next one itself; a second chain would double the rate.
      if (stopped || document.hidden || running) return;
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
      void run();
    };
    schedule();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped = true;
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled, ms]);
}

/**
 * A visually hidden heading for a list, plus a way to move focus to it. Use it after a row is
 * removed: the dialog hands focus back to the button that opened it, but that button is gone.
 * Put `heading` in every state the list can end up in (including empty).
 */
export function useListHeading(label: string, level: 2 | 3 = 3) {
  const ref = useRef<HTMLHeadingElement>(null);
  const [asked, setAsked] = useState(0);
  useEffect(() => {
    if (asked > 0) ref.current?.focus();
  }, [asked]);
  const H = level === 2 ? "h2" : "h3";
  const heading = (
    <H ref={ref} tabIndex={-1} className="sr-only">
      {label}
    </H>
  );
  const focusHeading = useCallback(() => setAsked((n) => n + 1), []);
  return { heading, focusHeading };
}

/**
 * WAI-ARIA tabs. Arrow keys, Home and End move between tabs and open them.
 * `children(id)` is called for every tab, so only the open one needs to render content.
 */
export function Tabs<T extends string>({
  label,
  tabs,
  active,
  onChange,
  children,
}: {
  label: string;
  tabs: { id: T; label: string }[];
  active: T;
  onChange: (id: T) => void;
  children: (id: T) => ReactNode;
}) {
  const base = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const tabId = (id: string) => `${base}-tab-${id}`;
  const panelId = (id: string) => `${base}-panel-${id}`;

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const next = nextTabIndex(index, e.key, tabs.length);
    if (next === null) return;
    e.preventDefault();
    onChange(tabs[next].id);
    refs.current[next]?.focus();
  };

  return (
    <div>
      <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-border-subtle px-3">
        {tabs.map((t, i) => {
          const on = t.id === active;
          return (
            <button
              key={t.id}
              ref={(el) => {
                refs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={tabId(t.id)}
              aria-selected={on}
              aria-controls={panelId(t.id)}
              tabIndex={on ? 0 : -1}
              onClick={() => onChange(t.id)}
              onKeyDown={(e) => onKeyDown(e, i)}
              className={cn(
                "-mb-px whitespace-nowrap border-b-2 px-3 py-3 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary",
                on ? "border-primary text-primary" : "border-transparent text-ink-secondary hover:text-ink",
              )}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      {tabs.map((t) => (
        <div key={t.id} role="tabpanel" id={panelId(t.id)} aria-labelledby={tabId(t.id)} hidden={t.id !== active} tabIndex={0} className="focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
          {t.id === active ? children(t.id) : null}
        </div>
      ))}
    </div>
  );
}

const STATE_STYLE: Record<KbDocState, string> = {
  ready: "bg-success/10 text-success",
  gaps: "bg-amber-50 text-amber-700",
  failed: "bg-danger/10 text-danger",
  reading: "bg-primary/10 text-primary-dark",
};

/** The state word is always shown, so colour is never the only signal. */
export function StatePill({ state, label }: { state: KbDocState; label: string }) {
  return <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-medium", STATE_STYLE[state])}>{label}</span>;
}

export function MainResourceBadge() {
  return <span className="inline-flex rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary-dark">Main resource</span>;
}

/** "That is not here": an unknown collection or file. */
export function NotFoundNote({ message, backHref, backLabel }: { message: string; backHref: string; backLabel: string }) {
  return (
    <div className="rounded-2xl border border-border-subtle bg-white px-5 py-10 text-center" role="status">
      <h2 className="text-sm font-semibold text-ink">Not found</h2>
      <p className="mt-1 text-sm text-ink-secondary">{message}</p>
      <Link href={backHref} className={`${BTN_SECONDARY} mt-4`}>
        {backLabel}
      </Link>
    </div>
  );
}

/** Heading and one line, with one action, for a list with nothing in it. */
export function EmptyNote({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="px-5 py-10 text-center" role="status">
      <p className="mx-auto max-w-md text-sm text-ink-secondary">{children}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

/**
 * Asks before something that cannot be undone. `onConfirm` throws to keep the dialog open
 * and show the message (for example the server's own text).
 */
export function ConfirmDialog({
  title,
  confirmLabel,
  onConfirm,
  onClose,
  children,
}: {
  title: string;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
  children: ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const confirm = async () => {
    setBusy(true);
    setError("");
    try {
      await onConfirm();
    } catch (e) {
      if (mounted.current) {
        setError(errorText(e, "That did not work. Please try again."));
        setBusy(false);
      }
    }
  };

  return (
    <KbDialog
      open
      title={title}
      onClose={busy ? () => undefined : onClose}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className={BTN_SECONDARY} data-autofocus>
            Cancel
          </button>
          <button type="button" onClick={confirm} disabled={busy} className={BTN_DANGER}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </>
      }
    >
      <div className="space-y-2 text-ink-secondary">{children}</div>
      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}
    </KbDialog>
  );
}

/** One box and a Save button: used to create and to rename a collection. */
export function NameDialog({
  title,
  intro,
  initial,
  submitLabel,
  onSubmit,
  onClose,
}: {
  title: string;
  intro?: string;
  initial: string;
  submitLabel: string;
  onSubmit: (name: string) => Promise<void>;
  onClose: () => void;
}) {
  const formId = useId();
  const inputId = useId();
  const [name, setName] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const problem = nameProblem(name);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onSubmit(name.trim());
    } catch (err) {
      if (mounted.current) {
        setError(errorText(err, "Could not save the name. Please try again."));
        setBusy(false);
      }
    }
  };

  return (
    <KbDialog
      open
      title={title}
      onClose={busy ? () => undefined : onClose}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className={BTN_SECONDARY}>
            Cancel
          </button>
          <button type="submit" form={formId} disabled={busy} className={BTN_PRIMARY}>
            {busy ? "Saving…" : submitLabel}
          </button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} className="space-y-3">
        {intro && <p className="text-ink-secondary">{intro}</p>}
        <Field id={inputId} label="Collection name" error={error}>
          <input
            id={inputId}
            data-autofocus
            className={INPUT}
            value={name}
            maxLength={80}
            onChange={(e) => setName(e.target.value)}
            placeholder="For example: Product guides"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${inputId}-error` : undefined}
            autoComplete="off"
          />
        </Field>
      </form>
    </KbDialog>
  );
}
