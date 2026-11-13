"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Check, Copy } from "lucide-react";
import { api, type AutoMessageEvents, type AutoMessageSetup, type PrivateSendStatus } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { ghostBtn, primaryBtn } from "./shared";

const COPIED_FLASH_MS = 2000;
const ROW = "flex flex-col gap-3 border-t border-border-subtle px-3 py-4 first:border-t-0 sm:flex-row sm:items-center sm:justify-between sm:px-4";

/** Static look-alike of the website form, so owners see what customers will get. */
function FormPreview() {
  return (
    <div className="grid max-w-[340px] gap-2.5 rounded-xl border border-[#e3e3e3] bg-white p-4 shadow-sm" aria-hidden>
      <p className="text-[15px] font-semibold text-[#1a1a1a]">Get details on WhatsApp</p>
      <div className="rounded-lg border border-[#cfcfcf] px-3 py-2 text-[13px] text-[#9a9a9a]">Your name</div>
      <div className="rounded-lg border border-[#cfcfcf] px-3 py-2 text-[13px] text-[#9a9a9a]">WhatsApp number</div>
      <div className="rounded-lg bg-primary-800 py-2 text-center text-[13px] font-semibold text-white">Send me details</div>
      <p className="text-[11px] text-[#666]">We&apos;ll send you updates on WhatsApp.</p>
    </div>
  );
}

/** The two lines a website manager pastes in. data-event picks which event the form fires. */
function formSnippet(scriptUrl: string, eventKey: string): string {
  return `<div data-anril-form data-event="${eventKey}"></div>\n<script src="${scriptUrl}" async></script>`;
}

function CopyCode({ text, eventLabel }: { text: string; eventLabel: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setFailed(false);
    } catch {
      setFailed(true);
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setCopied(false);
      setFailed(false);
    }, COPIED_FLASH_MS);
  }

  return (
    <>
      <button type="button" onClick={() => void copy()} aria-label={`Copy website form code for ${eventLabel}`} className={primaryBtn}>
        {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "Copied" : "Copy code"}
      </button>
      <span role="status" className="sr-only">
        {copied ? "Code copied" : failed ? "Couldn't copy" : ""}
      </span>
      {failed && (
        <span role="alert" className="font-body text-xs text-danger">
          Couldn&apos;t copy. Select the code and copy it by hand.
        </span>
      )}
    </>
  );
}

function WebsiteFormRow({
  canManage,
  setup,
  events,
  onCreateLink,
  creating,
  createError,
}: {
  canManage: boolean;
  setup: AutoMessageSetup | null;
  events: AutoMessageEvents | null;
  onCreateLink: () => void;
  creating: boolean;
  createError: string | null;
}) {
  const [eventKey, setEventKey] = useState("interested");
  const options = [...(events?.builtin ?? []), ...(events?.custom ?? [])];
  const chosen = options.find((e) => e.key === eventKey);
  const title = (
    <div className="min-w-0">
      <h3 className="font-display text-sm font-bold text-ink">Website form</h3>
      <p className="mt-0.5 font-body text-xs text-ink-secondary">Send this code to whoever manages your website.</p>
    </div>
  );

  if (!canManage) {
    return (
      <li className={ROW}>
        {title}
        <p className="font-body text-xs text-ink-secondary">Only an admin can copy the code.</p>
      </li>
    );
  }

  if (!setup?.form_script_url) {
    return (
      <li className={ROW}>
        {title}
        <div className="flex flex-col items-start gap-1">
          <button type="button" onClick={onCreateLink} disabled={creating} className={primaryBtn}>
            {creating ? "Creating…" : "Create my link"}
          </button>
          {createError && (
            <p role="alert" className="font-body text-xs font-semibold text-danger">
              {createError}
            </p>
          )}
        </div>
      </li>
    );
  }

  return (
    <li className="space-y-3 border-t border-border-subtle px-3 py-4 first:border-t-0 sm:px-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {title}
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="form-event" className="font-body text-xs text-ink-secondary">
            Fires:
          </label>
          <Select
            size="sm"
            id="form-event"
            value={eventKey}
            onChange={setEventKey}
            className="w-auto min-w-[140px]"
            options={
              options.length === 0
                ? [{ value: "interested", label: "Interested" }]
                : options.map((o) => ({ value: o.key, label: o.label }))
            }
          />
          <CopyCode text={formSnippet(setup.form_script_url, eventKey)} eventLabel={chosen?.label ?? "Interested"} />
        </div>
      </div>
      <div>
        <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-wide text-ink-secondary">Customers see</p>
        <FormPreview />
      </div>
    </li>
  );
}

export function SourcesSection({
  canManage,
  privateSend,
}: {
  canManage: boolean;
  /** Plug-in status from /private-send; non-null means this account sends from its own server. */
  privateSend: PrivateSendStatus | null;
}) {
  const [setup, setSetup] = useState<AutoMessageSetup | null>(null);
  const [events, setEvents] = useState<AutoMessageEvents | null>(null);
  const [loaded, setLoaded] = useState(!canManage);
  const [loadError, setLoadError] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(false);
    try {
      const [s, e] = await Promise.all([api.autoMessages.setup(), api.autoMessages.events()]);
      setSetup(s);
      setEvents(e);
    } catch {
      setLoadError(true);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (canManage) void load();
    else {
      api.autoMessages.events().then(setEvents).catch(() => undefined);
    }
  }, [canManage, load]);

  async function createLink() {
    setCreating(true);
    setCreateError(null);
    try {
      setSetup(await api.autoMessages.rotateToken());
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Couldn't create the link. Try again.");
    } finally {
      setCreating(false);
    }
  }

  const ownServer = privateSend !== null || Boolean(setup?.private_send_on);

  return (
    <ul className="m-0 list-none overflow-hidden rounded-[24px] border border-border-subtle bg-white p-0">
      {!loaded ? (
        <li className="h-24 animate-pulse bg-border-subtle" aria-busy="true" aria-label="Loading" />
      ) : loadError ? (
        <li role="alert" className="px-4 py-4 font-body text-sm text-ink-secondary">
          Couldn&apos;t load the website form.{" "}
          <button type="button" onClick={() => void load()} className={`${ghostBtn} ml-1`}>
            Try again
          </button>
        </li>
      ) : ownServer ? (
        <li className="px-3 py-4 sm:px-4">
          <h3 className="font-display text-sm font-bold text-ink">Website form</h3>
          <p className="mt-0.5 font-body text-xs text-ink-secondary">
            This account sends from its own server, so the website form is off.
          </p>
        </li>
      ) : (
        <WebsiteFormRow
          canManage={canManage}
          setup={setup}
          events={events}
          onCreateLink={() => void createLink()}
          creating={creating}
          createError={createError}
        />
      )}
      <li className={ROW}>
        <div className="min-w-0">
          <h3 className="font-display text-sm font-bold text-ink">Your app or server</h3>
          <p className="mt-0.5 font-body text-xs text-ink-secondary">Your app sends a template ID or an event (your choice) — set up on the Developer page</p>
        </div>
        <Link href="/dashboard/developer" className={ghostBtn}>
          Developer page →
        </Link>
      </li>
    </ul>
  );
}
