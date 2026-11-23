"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { FIRST_SETUP_STEPS, firstSetupApi, setAiAgentOn, type FirstSetupStep } from "@/lib/firstSetupApi";
import { InterviewQuestionsForm, InterviewReview, StarterStep } from "./WorkspaceSteps";
import type { InterviewDraft } from "@/lib/api";
import { GSTIN_PATTERN } from "./helpers";

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

function LinkStep({ title, text, links, onNext }: { title: string; text: string; links: { href: string; label: string }[]; onNext: () => void }) {
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
      </div>
      <button type="button" onClick={onNext} className="btn-primary mt-4 w-full justify-center">
        Done, next step
      </button>
      <p className="mt-2 text-center font-body text-xs text-ink-muted">Each link opens in a new tab, so you can come straight back here.</p>
    </div>
  );
}

/** Do you have GST? Saved with the rest of the business details. */
function GstCard({ onNext }: { onNext: () => void }) {
  const [hasGst, setHasGst] = useState<"yes" | "no" | null>(null);
  const [gstin, setGstin] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const clean = gstin.trim().toUpperCase();

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (hasGst === "yes" && clean) {
        if (!GSTIN_PATTERN.test(clean)) {
          setError("That GSTIN doesn't look right. It has 15 characters, like 33ABCDE1234F1Z5.");
          setSaving(false);
          return;
        }
        // The details are saved as one block, so read what is there first and change only the GSTIN.
        const current = await api.businessProfile.get();
        await api.businessProfile.save({ ...current, gstin: clean });
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
      <p className={sub}>Your GSTIN goes on your bills. You can add or change it later in Settings.</p>
      {error && <div className={errorBox}>{error}</div>}
      <div className="grid grid-cols-2 gap-2">
        {(["yes", "no"] as const).map((v) => (
          <button
            key={v}
            type="button"
            aria-pressed={hasGst === v}
            onClick={() => setHasGst(v)}
            className={`rounded-xl border px-4 py-3 font-body text-sm font-medium ${hasGst === v ? "border-primary bg-primary/5 text-ink" : "border-border text-ink"}`}
          >
            {v === "yes" ? "Yes" : "No"}
          </button>
        ))}
      </div>
      {hasGst === "yes" && (
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

function AiStep({ onNext }: { onNext: () => void }) {
  const [on, setOn] = useState<boolean | null>(null);
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

  return (
    <div className={card}>
      <h1 className={heading}>{TITLES.ai}</h1>
      <p className={sub}>
        First send yourself a test message on WhatsApp and see how it answers. When you are happy, switch the AI agent on. You can switch it off any time in Settings.
      </p>
      {error && <div className={errorBox}>{error}</div>}
      {on ? (
        <p className="rounded-xl bg-emerald-50 p-3 font-body text-sm text-emerald-800">Your AI agent is on.</p>
      ) : (
        <button type="button" onClick={turnOn} disabled={busy} className={outline}>
          {busy ? "Switching on…" : "Switch on the AI agent"}
        </button>
      )}
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
      {step === "connect" && (
        <LinkStep
          title={TITLES.connect}
          text="Connect your WhatsApp, Instagram and Facebook with one button. Meta's own charges are on top of your Anril plan. Razorpay is optional."
          links={[{ href: "/dashboard/settings/connect-channels", label: "Connect my accounts" }]}
          onNext={() => move(true)}
        />
      )}
      {step === "ai" && <AiStep onNext={() => move(true)} />}

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
