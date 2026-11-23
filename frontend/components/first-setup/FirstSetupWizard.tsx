"use client";
import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { FIRST_SETUP_STEPS, firstSetupApi, setAiAgentOn, type FirstSetupStep } from "@/lib/firstSetupApi";
import { InterviewQuestionsForm, InterviewReview, StarterStep } from "./WorkspaceSteps";
import type { InterviewDraft } from "@/lib/api";
import { GSTIN_PATTERN, asksForGstin, gstTypeFor, type GstChoice } from "./helpers";
import { ConnectStep } from "./ConnectStep";
import { setupHelpApi } from "@/lib/setupHelpApi";

// The 6 first-setup steps. Every step can be skipped, "Finish later" is always on screen, and each
// step saves through the screen that already owns that setting. Progress is remembered on the server,
// so coming back later picks up where the owner stopped.

const TITLES: Record<FirstSetupStep, string> = {
  business: "What is your business?",
  items: "What do you sell?",
  hours: "Open hours",
  alerts: "Who gets alerts?",
  connect: "Connect your accounts",
  ai: "Switch on your AI agent",
};

const card = "card rounded-3xl p-8";
const heading = "font-display text-xl font-bold text-ink mb-1";
const sub = "font-body text-sm text-ink-muted mb-6";
const errorBox = "mb-4 p-3 rounded-xl bg-red-50 text-red-700 font-body text-sm";
const outline =
  "w-full rounded-xl border border-border px-4 py-3 text-center font-body text-sm font-medium text-ink hover:border-primary hover:bg-primary/5";

function LinkStep({ title, text, links, onNext, extra }: { title: string; text: string; links: { href: string; label: string }[]; onNext: () => void; extra?: ReactNode }) {
  return (
    <div className={card}>
      <h1 className={heading}>{title}</h1>
      <p className={sub}>{text}</p>
      <div className="space-y-2">
        {links.map((l) => (
          <Link key={l.href} href={l.href} target="_blank" rel="noopener" className={`${outline} block`}>
            {l.label}
          </Link>
        ))}
        {extra}
      </div>
      <button type="button" onClick={onNext} className="btn-primary mt-4 w-full justify-center">
        Done, next step
      </button>
      <p className="mt-2 text-center font-body text-xs text-ink-muted">Each link opens in a new tab, so you can come straight back here.</p>
    </div>
  );
}

/** v9.2 #80: ask the Anril team to add the catalogue. One open ask per business, so a second tap changes nothing. */
function CatalogueHelp() {
  const [requested, setRequested] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setupHelpApi.catalogueStatus().then((r) => setRequested(r.requested)).catch(() => setRequested(false));
  }, []);

  async function ask() {
    setBusy(true);
    setError(null);
    try {
      await setupHelpApi.requestCatalogue();
      setRequested(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send your request. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (requested) {
    return (
      <p role="status" className="rounded-xl bg-primary/5 px-4 py-3 text-center font-body text-sm font-medium text-ink">
        Requested · we&apos;ll WhatsApp you
      </p>
    );
  }
  return (
    <div>
      {error && <p role="alert" className={errorBox}>{error}</p>}
      <button type="button" onClick={ask} disabled={busy || requested === null} className={`${outline} disabled:opacity-60`}>
        {busy ? "Sending…" : "Let the Anril team do it"}
      </button>
    </div>
  );
}

const GST_CHOICES: { value: GstChoice; label: string; hint: string }[] = [
  { value: "yes", label: "Yes", hint: "Registered" },
  { value: "composition", label: "Composition", hint: "Bill of supply" },
  { value: "no", label: "No", hint: "Simple bill" },
];

/** Do you have GST? Yes, Composition or No. Saved with the rest of the business details. */
function GstCard({ onNext }: { onNext: () => void }) {
  const [choice, setChoice] = useState<GstChoice | null>(null);
  const [gstin, setGstin] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const clean = gstin.trim().toUpperCase();

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (choice) {
        if (asksForGstin(choice) && clean && !GSTIN_PATTERN.test(clean)) {
          setError("That GSTIN doesn't look right. It has 15 characters, like 33ABCDE1234F1Z5.");
          setSaving(false);
          return;
        }
        // The details are saved as one block, so read what is there first and change only the GST fields.
        const current = await api.businessProfile.get();
        const next = { ...current, gst_type: gstTypeFor(choice), ...(asksForGstin(choice) && clean ? { gstin: clean } : {}) };
        await api.businessProfile.save(next);
      }
      onNext();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save. Please try again.");
      setSaving(false);
    }
  }

  return (
    <div className={card}>
      <h1 className={heading}>Do you have GST?</h1>
      <p className={sub}>
        Your GSTIN goes on your bills. A Composition business gets a Bill of supply, with no tax lines. You can add or change it later in Settings.
      </p>
      {error && <div className={errorBox}>{error}</div>}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {GST_CHOICES.map((c) => (
          <button
            key={c.value}
            type="button"
            aria-pressed={choice === c.value}
            onClick={() => setChoice(c.value)}
            className={`rounded-xl border px-4 py-3 font-body text-sm font-medium ${choice === c.value ? "border-primary bg-primary/5 text-ink" : "border-border text-ink"}`}
          >
            {c.label}
            <span className="block text-xs font-normal text-ink-secondary">{c.hint}</span>
          </button>
        ))}
      </div>
      {asksForGstin(choice) && (
        <div className="mt-4">
          <label htmlFor="fs-gstin" className="font-body text-sm font-medium text-ink mb-1.5 block">
            GSTIN (optional)
          </label>
          <input id="fs-gstin" value={gstin} onChange={(e) => setGstin(e.target.value)} maxLength={15} className="input" placeholder="33ABCDE1234F1Z5" autoCapitalize="characters" />
        </div>
      )}
      <button type="button" onClick={save} disabled={saving} className="btn-primary mt-5 w-full justify-center">
        {saving ? "Saving…" : "Save and continue"}
      </button>
    </div>
  );
}

function BusinessStep({ onNext }: { onNext: () => void }) {
  const [part, setPart] = useState<"type" | "questions" | "review" | "gst">("type");
  const [draft, setDraft] = useState<InterviewDraft | null>(null);
  if (part === "gst") return <GstCard onNext={onNext} />;
  if (part === "questions")
    return (
      <InterviewQuestionsForm
        onDrafted={(d) => {
          setDraft(d);
          setPart("review");
        }}
        onCancel={() => setPart("type")}
      />
    );
  if (part === "review" && draft) return <InterviewReview draft={draft} onDone={() => setPart("gst")} onBack={() => setPart("questions")} />;
  return <StarterStep onDone={() => setPart("gst")} onWantInterview={() => setPart("questions")} />;
}

// What each step's tick says in the "Your setup" list on the last step.
const SUMMARY: Record<Exclude<FirstSetupStep, "ai">, string> = {
  business: "Business type",
  items: "Catalogue",
  hours: "Open hours",
  alerts: "Who gets alerts",
  connect: "WhatsApp and Instagram connected",
};

/**
 * Step 6 (screen 85): try the AI agent in a test chat first, then switch it on. The switch unlocks after
 * the owner has opened the test chat (or when the agent is already on), so nobody turns it on blind.
 */
function AiStep({ done, onNext }: { done: FirstSetupStep[]; onNext: () => void }) {
  const [on, setOn] = useState<boolean | null>(null);
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.settings.getAiAutoReply().then((r) => setOn(r.enabled)).catch(() => setOn(null));
  }, []);

  async function turnOn() {
    setBusy(true);
    setError(null);
    try {
      await setAiAgentOn(true);
      setOn(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't switch it on. Please try again.");
    }
    setBusy(false);
  }

  const canSwitch = tried || on === true;

  return (
    <div className={card}>
      <h1 className={heading}>{TITLES.ai}</h1>
      <p className={sub}>It replies to your customers using your Catalogue and business details. Try it first: nothing is sent to anyone.</p>
      {error && <div className={errorBox}>{error}</div>}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-3">
          <Link href="/dashboard/brain?section=test" target="_blank" rel="noopener" onClick={() => setTried(true)} className={`${outline} block`}>
            💬 Try it in a test chat
          </Link>
          {on ? (
            <p className="rounded-xl bg-emerald-50 p-3 font-body text-sm text-emerald-800">Your AI agent is on. You can take over any chat any time.</p>
          ) : (
            <>
              <button type="button" onClick={turnOn} disabled={busy || !canSwitch} className={`${outline} disabled:cursor-not-allowed disabled:opacity-50`}>
                {busy ? "Switching on…" : "Switch on the AI agent"}
              </button>
              {!canSwitch && <p className="font-body text-xs text-ink-secondary">Try the test chat first, then switch it on here.</p>}
            </>
          )}
        </div>
        <div className="rounded-2xl border border-border p-4">
          <p className="mb-2 font-body text-sm font-semibold text-ink">Your setup</p>
          <ul className="space-y-1.5 font-body text-sm">
            {(Object.keys(SUMMARY) as (keyof typeof SUMMARY)[]).map((k) => (
              <li key={k} className={done.includes(k) ? "text-ink" : "text-ink-secondary"}>
                {done.includes(k) ? "✓ " : "○ "}
                {SUMMARY[k]}
                {!done.includes(k) && " · skipped"}
              </li>
            ))}
          </ul>
        </div>
      </div>
      <button type="button" onClick={onNext} className="btn-primary mt-4 w-full justify-center">
        Finish setup
      </button>
    </div>
  );
}

export function FirstSetupWizard({ onFinish }: { onFinish: () => void }) {
  const [step, setStep] = useState<FirstSetupStep>("business");
  const [done, setDone] = useState<FirstSetupStep[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    firstSetupApi
      .progress()
      .then((p) => {
        setStep(p.step);
        setDone(p.done_steps);
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  const index = FIRST_SETUP_STEPS.indexOf(step);

  // Next and Skip both move on; only Next marks the step done.
  function move(markDone: boolean) {
    const nextDone = markDone && !done.includes(step) ? [...done, step] : done;
    const next = FIRST_SETUP_STEPS[index + 1];
    setDone(nextDone);
    // Saved in the background: a slow save never blocks the owner.
    firstSetupApi.saveProgress({ step: next ?? step, done_steps: nextDone }).catch(() => {});
    if (next) setStep(next);
    else onFinish();
  }

  if (!loaded) return <div className="h-64 rounded-3xl bg-border-subtle animate-pulse" />;

  return (
    <div>
      <p className="mb-3 text-center font-body text-xs font-medium text-ink-muted">
        Step {index + 1} of {FIRST_SETUP_STEPS.length}
      </p>
      {step === "business" && <BusinessStep onNext={() => move(true)} />}
      {step === "items" && (
        <LinkStep
          title={TITLES.items}
          text="Add your items one by one, or upload a price list (Excel, PDF or a photo of your price board). You can also skip this and do it later."
          links={[{ href: "/dashboard/catalog", label: "Add items or upload a price list" }]}
          extra={<CatalogueHelp />}
          onNext={() => move(true)}
        />
      )}
      {step === "hours" && (
        <LinkStep
          title={TITLES.hours}
          text="Write your opening hours in your business description, so the AI agent can tell customers when you are open."
          links={[{ href: "/dashboard/knowledge?tab=description", label: "Write my open hours" }]}
          onNext={() => move(true)}
        />
      )}
      {step === "alerts" && (
        <LinkStep
          title={TITLES.alerts}
          text="Choose which people hear about a hot customer, a customer who wants to talk to a person, and your evening summary."
          links={[{ href: "/dashboard/settings/notifications", label: "Choose who gets alerts" }]}
          onNext={() => move(true)}
        />
      )}
      {step === "connect" && <ConnectStep onNext={() => move(true)} />}
      {step === "ai" && <AiStep done={done} onNext={() => move(true)} />}

      <div className="mt-4 flex items-center justify-between">
        <button type="button" onClick={onFinish} className="font-body text-sm font-medium text-ink-muted hover:text-ink">
          Finish later
        </button>
        {step !== "business" && (
          <button type="button" onClick={() => move(false)} className="font-body text-sm font-medium text-ink-muted hover:text-ink">
            Skip this step
          </button>
        )}
      </div>
    </div>
  );
}
