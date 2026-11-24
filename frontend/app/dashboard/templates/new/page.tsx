"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  Check,
  Copy,
  FileCode,
  LayoutGrid,
  Lock,
  PenLine,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { LANGUAGES, CATEGORIES, detectVariables } from "../types";
import type { Button } from "../types";
import {
  UTILITY_TIP,
  bodyBlockers,
  buttonBlockers,
  cleanFooter,
  cleanHeader,
  footerBlockers,
  headerBlockers,
  sampleBlockers,
} from "../template-rules";
import type { Blocker } from "../template-rules";
import FieldMessages, { SampleInputs, focusFirst, useFixNotes } from "../components/field-messages";
import ButtonBuilder from "../components/button-builder";
import VariableInserter from "../components/variable-inserter";
import PlaceholderGuide from "../components/placeholder-guide";
import WhatsAppPreview from "../components/whatsapp-preview";
import { useAuthRole } from "../../contexts/AuthRoleContext";
import { prefillFromTemplate, takePrefill } from "../template-prefill";
import type { TemplatePrefill } from "../template-prefill";
import AiWriter from "../components/ai-writer";
import CopyPicker from "../components/copy-picker";

type Category = "MARKETING" | "UTILITY" | "AUTHENTICATION";
type HeaderKind = "NONE" | "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT";

const CATEGORY_COST: Record<Category, { text: string; cls: string }> = {
  MARKETING: { text: "costs more", cls: "text-[#b3361b]" },
  UTILITY: { text: "costs less", cls: "text-emerald-700" },
  AUTHENTICATION: { text: "costs less", cls: "text-emerald-700" },
};
const HEADER_KINDS: { value: HeaderKind; label: string }[] = [
  { value: "NONE", label: "None" },
  { value: "TEXT", label: "Aa Text" },
  { value: "IMAGE", label: "Image" },
  { value: "VIDEO", label: "Video" },
  { value: "DOCUMENT", label: "Document" },
];

/** A section card with its number, or a green tick once nothing in it needs fixing. */
function Section({
  n, title, hint, done, active = false, children, className = "",
}: {
  n: number; title: string; hint?: string; done: boolean; active?: boolean; children: React.ReactNode; className?: string;
}) {
  return (
    <section
      className={`rounded-2xl border bg-white p-5 shadow-sm md:p-6 ${
        active ? "border-primary-300 ring-4 ring-primary-50" : "border-[#e7e2da]"
      } ${className}`}
    >
      <div className="mb-4 flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[13px] font-bold ${
            done ? "bg-emerald-50 text-emerald-600" : "bg-primary text-white"
          }`}
          aria-hidden="true"
        >
          {done ? <Check size={15} strokeWidth={3} /> : n}
        </span>
        <h2 className="font-display text-base font-bold text-ink">{title}</h2>
        {hint && <span className="text-[12.5px] text-ink-muted">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

export default function NewTemplatePage() {
  const router = useRouter();
  const { role, permissions } = useAuthRole();
  const canManageTemplates = role === "owner" || permissions.includes("templates.manage");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form State
  const [name, setName] = useState("");
  const [category, setCategory] = useState<Category>("MARKETING");
  const [language, setLanguage] = useState("en");

  // Content State
  const [headerType, setHeaderType] = useState<HeaderKind>("NONE");
  const [headerText, setHeaderText] = useState("");
  const [headerMediaUrl, setHeaderMediaUrl] = useState("");
  // Local copy of the chosen file for the preview; Meta's handle can't be displayed.
  const [mediaPreview, setMediaPreview] = useState<{ url: string; name: string } | null>(null);
  useEffect(() => () => { if (mediaPreview) URL.revokeObjectURL(mediaPreview.url); }, [mediaPreview]);
  const [uploadingMedia, setUploadingMedia] = useState(false);
  const [bodyText, setBodyText] = useState("");
  const [footerText, setFooterText] = useState("");

  // Sample values Meta's reviewer sees for each variable
  const [bodySamples, setBodySamples] = useState<Record<number, string>>({});
  const [headerSample, setHeaderSample] = useState("");
  const { notes, show } = useFixNotes();

  // Buttons State
  const [buttons, setButtons] = useState<Button[]>([]);

  // How the form was started, and the live preview's mode
  const [start, setStart] = useState<"blank" | "copy" | "ai">("blank");
  const [copyOpen, setCopyOpen] = useState(false);
  const [previewWithSamples, setPreviewWithSamples] = useState(true);

  // Filled in from "Copy" / "Change to Utility" on the Templates page, from "Copy one of mine", or a Write with AI draft
  const [prefillSource, setPrefillSource] = useState("");
  function applyPrefill(p: TemplatePrefill) {
    setName(p.name);
    setCategory(p.category);
    setLanguage(p.language);
    setHeaderType(p.headerType);
    setHeaderText(p.headerText);
    setHeaderMediaUrl("");
    setMediaPreview(null);
    setBodyText(p.bodyText);
    setFooterText(p.footerText);
    setButtons(p.buttons);
    setBodySamples({});
    setHeaderSample("");
    setPrefillSource(p.source);
    setError(null);
  }
  useEffect(() => {
    const p = takePrefill();
    if (p) applyPrefill(p);
    // "Write with AI" on the Templates page opens this page with the AI box open
    if (new URLSearchParams(window.location.search).get("ai") === "1") setStart("ai");
  }, []);

  const generatedName = name
    .toLowerCase()
    .replace(/[^a-z0-9\s_]/g, "")
    .trim()
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");

  const hasContent = !!(name || bodyText || headerText || footerText || buttons.length);
  function startBlank() {
    if (hasContent && !confirm("Clear the form and start again?")) return;
    applyPrefill({ name: "", category: "MARKETING", language: "en", headerType: "NONE", headerText: "", bodyText: "", footerText: "", buttons: [], source: "" });
    setStart("blank");
  }

  // Media upload handler
  async function handleMediaUpload(file: File) {
    if (!canManageTemplates) {
      setError("Read-only role: media upload is disabled.");
      return;
    }
    setMediaPreview({ url: URL.createObjectURL(file), name: file.name });
    setUploadingMedia(true);
    setError(null);
    try {
      const authHeaders = await getAuthHeaders();
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`${API_URL}/api/v1/templates/upload-media`, {
        method: "POST",
        headers: authHeaders,
        body: formData,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || "Couldn't upload the file. Please try again.");
      }

      const data = await res.json();
      // Meta resumable upload returns header_handle
      setHeaderMediaUrl(data.header_handle);
    } catch (e) {
      setMediaPreview(null);
      setError(e instanceof Error ? e.message : "Media upload failed");
    } finally {
      setUploadingMedia(false);
    }
  }

  function clearMedia() {
    setMediaPreview(null);
    setHeaderMediaUrl("");
  }

  // Meta's rules, per section. Submit stays disabled until all of them are clear.
  const headerVars = headerType === "TEXT" ? detectVariables(headerText) : [];
  const blockers = useMemo(() => {
    const info: Blocker[] = generatedName
      ? []
      : [{ fieldId: "template-name", message: "Add a template name", inline: false }];
    const header: Blocker[] = [];
    if (headerType === "TEXT") {
      if (!headerText.trim()) header.push({ fieldId: "template-header", message: "Add the header text", inline: false });
      header.push(...headerBlockers(headerText, "template-header"));
      if (headerVars.length === 1 && !headerSample.trim()) {
        header.push({ fieldId: "template-header-sample-1", message: "Add a sample for the header variable.", inline: true });
      }
    } else if (headerType !== "NONE" && !headerMediaUrl) {
      header.push({ fieldId: "template-header-upload", message: "Upload the header file", inline: false });
    }
    const bodyRules = bodyBlockers(bodyText, "template-body");
    const samples = bodyRules.length ? [] : sampleBlockers(bodyText, bodySamples, "template-body-sample-");
    const footer = footerBlockers(footerText, "template-footer");
    const btns = buttonBlockers(buttons);
    return { info, header, bodyRules, samples, footer, btns, all: [...info, ...header, ...bodyRules, ...samples, ...footer, ...btns] };
  }, [generatedName, headerType, headerText, headerVars.length, headerSample, headerMediaUrl, bodyText, bodySamples, footerText, buttons]);

  // "Check before sending to Meta": the same rules, in plain words
  const checks = [
    { ok: blockers.info.length === 0, text: "Name is fine" },
    { ok: !!bodyText.trim() && blockers.bodyRules.length === 0, text: "Message follows Meta's rules" },
    { ok: !!bodyText.trim() && blockers.bodyRules.length === 0 && blockers.samples.length === 0, text: "Every {{ }} has a sample" },
    { ok: blockers.header.length === 0, text: "Header is complete" },
    { ok: blockers.footer.length === 0 && blockers.btns.length === 0, text: "Footer and buttons are fine" },
  ];
  const fixCount = blockers.all.length;

  // Submit template to API
  async function handleSubmit() {
    if (!canManageTemplates) {
      setError("Read-only role: submitting templates to Meta is disabled.");
      return;
    }
    if (blockers.all.length) {
      focusFirst(blockers.all);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const authHeaders = await getAuthHeaders();
      const payload = {
        name: generatedName,
        category,
        language,
        body_text: bodyText.trim(),
        body_examples: detectVariables(bodyText).map((n) => (bodySamples[n] ?? "").trim()),
        header_text: headerType === "TEXT" ? headerText.trim() : null,
        header_example: headerVars.length === 1 ? headerSample.trim() : null,
        header_media_type: headerType !== "NONE" && headerType !== "TEXT" ? headerType : null,
        header_media_url: headerType !== "NONE" && headerType !== "TEXT" ? headerMediaUrl : null,
        footer_text: footerText.trim() || null,
        buttons: buttons.length > 0 ? buttons : null,
      };

      const res = await fetch(`${API_URL}/api/v1/templates/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        // Nothing was saved: the form stays filled in so it can be fixed and resent.
        const text = await res.text();
        let detail = text;
        try { detail = JSON.parse(text).detail ?? text; } catch { /* plain text */ }
        throw new Error(detail || "Failed to submit template to WhatsApp");
      }

      router.push("/dashboard/templates");
    } catch (e) {
      setError(e instanceof Error ? e.message : "An unexpected error occurred");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setLoading(false);
    }
  }

  // Quick select helper for category
  const selectCategory = (val: Category) => {
    setCategory(val);
    if (val === "AUTHENTICATION") {
      // Setup default OTP configuration
      setHeaderType("NONE");
      setBodyText("{{1}} is your verification code. For security, do not share this code.");
      setFooterText("This code expires in 10 minutes.");
      setButtons([{ type: "COPY_CODE", text: "Copy Code" }]);
    } else if (category === "AUTHENTICATION") {
      // leaving the fixed OTP wording: start the message fresh
      setBodyText("");
      setFooterText("");
      setButtons([]);
    }
  };

  const isAuth = category === "AUTHENTICATION";
  const startChip = (on: boolean) =>
    `inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-[13px] font-semibold transition ${
      on ? "border-primary bg-primary-50 text-primary-800 ring-2 ring-primary-100" : "border-[#e2ddd5] bg-white text-ink hover:border-primary-200"
    }`;

  return (
    <div className="w-full pb-28">
      <div className="mb-4">
        <Link
          href="/dashboard/templates"
          className="inline-flex items-center gap-2 rounded-xl border border-[#e2e8f0] px-3 py-1.5 font-label text-sm font-semibold text-[#0A1528]/80 transition-all hover:bg-[#f1f5f9] hover:text-[#0A1528]"
        >
          <ArrowLeft size={14} /> Back to Templates
        </Link>
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        {/* ── Left: the whole form on one page ── */}
        <div className="min-w-0 space-y-4">
          {canManageTemplates && (
            <div className="relative flex flex-wrap items-center gap-2 rounded-2xl border border-primary-100 bg-primary-50/60 px-4 py-3">
              <span className="mr-1 text-[13.5px] font-bold text-ink">Start from:</span>
              <button type="button" className={startChip(start === "blank")} onClick={startBlank}>
                <PenLine size={13} aria-hidden="true" /> Blank
              </button>
              <button type="button" className={startChip(start === "copy")} aria-expanded={copyOpen} onClick={() => setCopyOpen((v) => !v)}>
                <Copy size={13} aria-hidden="true" /> Copy one of mine
              </button>
              <button type="button" className={startChip(start === "ai")} onClick={() => setStart(start === "ai" ? "blank" : "ai")}>
                <Sparkles size={13} aria-hidden="true" /> Write with AI
              </button>
              <Link href="/dashboard/templates/carousel" className={startChip(false)}>
                <LayoutGrid size={13} aria-hidden="true" /> Carousel
              </Link>
              {copyOpen && (
                <CopyPicker
                  onClose={() => setCopyOpen(false)}
                  onPick={(t) => {
                    applyPrefill(prefillFromTemplate(t));
                    setStart("copy");
                    setCopyOpen(false);
                  }}
                />
              )}
            </div>
          )}

          {canManageTemplates && start === "ai" && (
            <AiWriter
              defaultOpen
              language={language}
              onUse={(p) => {
                applyPrefill({ ...p, source: "Draft added below. Check each section and add samples for any {{ }}, then submit it to Meta." });
              }}
            />
          )}

          {prefillSource && (
            <div className="flex items-start gap-2.5 rounded-xl border border-primary-200 bg-primary-50/70 p-4 text-sm text-primary-800">
              <Sparkles size={16} className="mt-0.5 shrink-0" />
              <p className="font-body">
                {prefillSource}
                {(headerType === "IMAGE" || headerType === "VIDEO" || headerType === "DOCUMENT") && !headerMediaUrl && " Add the header file again under Header."}
              </p>
            </div>
          )}

          {error && (
            <div className="flex animate-slide-up items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <p className="font-body">{error}</p>
            </div>
          )}

          {/* 1. Name, type and language */}
          <Section n={1} title="Name, type and language" done={blockers.info.length === 0}>
            <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <div className="min-w-0">
                <label htmlFor="template-name" className="mb-1.5 block text-[13px] font-semibold text-ink">Template name</label>
                <input
                  id="template-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. payment_reminder or Diwali offer"
                  className="input font-mono"
                />
                <p className="mt-1.5 text-[12px] text-ink-muted">
                  {generatedName ? (
                    <>Sent to Meta as <span className="rounded bg-surface-subtle px-1.5 py-0.5 font-mono font-semibold text-ink">{generatedName}</span></>
                  ) : (
                    "Small letters, numbers and _ only. We fix it as you type."
                  )}
                </p>
              </div>
              <div className="min-w-0">
                <span className="mb-1.5 block text-[13px] font-semibold text-ink">Language</span>
                <Select
                  aria-label="Language"
                  value={language}
                  onChange={setLanguage}
                  options={LANGUAGES.map((lang) => ({ value: lang.code, label: lang.label }))}
                />
                <p className="mt-1.5 text-[12px] text-ink-muted">The language Meta checks the words in.</p>
              </div>
            </div>
            <div className="mt-4">
              <span className="mb-1.5 block text-[13px] font-semibold text-ink">
                Type <span className="font-normal text-ink-muted">(Meta calls it Category)</span>
              </span>
              <div className="grid gap-2.5 sm:grid-cols-3" role="radiogroup" aria-label="Type">
                {CATEGORIES.map((c) => {
                  const on = category === c.value;
                  return (
                    <button
                      key={c.value}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      onClick={() => selectCategory(c.value)}
                      className={`min-w-0 rounded-xl border p-3.5 text-left transition ${
                        on ? "border-primary bg-primary-50/50 ring-2 ring-primary-100" : "border-[#e2ddd5] bg-white hover:border-primary-200"
                      }`}
                    >
                      <span className="flex items-center gap-2 whitespace-nowrap text-sm font-bold text-ink">
                        <span className={`h-3.5 w-3.5 shrink-0 rounded-full ${on ? "border-[4.5px] border-primary" : "border-[1.5px] border-[#9aa3b2]"}`} aria-hidden="true" />
                        {c.label}
                      </span>
                      <span className="mt-1 block text-[12px] leading-snug text-ink-muted">{c.description}</span>
                      <span className={`mt-1.5 block text-[12px] font-bold ${CATEGORY_COST[c.value].cls}`}>{CATEGORY_COST[c.value].text}</span>
                    </button>
                  );
                })}
              </div>
              {category === "UTILITY" && <FieldMessages id="category-messages" tip={UTILITY_TIP} />}
            </div>
          </Section>

          {/* 2. Header */}
          <Section n={2} title="Header" hint="optional · a bold line or a picture on top" done={blockers.header.length === 0}>
            {isAuth ? (
              <p className="flex items-start gap-2.5 rounded-xl border border-border-subtle bg-surface-subtle p-3.5 text-[13px] text-ink-muted">
                <Lock size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                Login-code templates have no header (Meta&apos;s rule).
              </p>
            ) : (
              <>
                <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Header">
                  {HEADER_KINDS.map((h) => (
                    <button
                      key={h.value}
                      type="button"
                      role="radio"
                      aria-checked={headerType === h.value}
                      onClick={() => {
                        setHeaderType(h.value);
                        setHeaderText("");
                        setHeaderSample("");
                        clearMedia();
                      }}
                      className={startChip(headerType === h.value)}
                    >
                      {h.label}
                    </button>
                  ))}
                </div>

                {headerType === "TEXT" && (
                  <div className="mt-4 max-w-xl">
                    <label htmlFor="template-header" className="mb-1.5 block text-[13px] font-semibold text-ink">
                      Header text <span className="font-normal text-ink-muted">· up to 60, one {"{{1}}"} allowed</span>
                    </label>
                    <input
                      id="template-header"
                      value={headerText}
                      onChange={(e) => {
                        const cleaned = cleanHeader(e.target.value);
                        show("header", cleaned.note);
                        setHeaderText(cleaned.text);
                      }}
                      maxLength={60}
                      placeholder="e.g. Payment reminder"
                      aria-describedby="template-header-messages"
                      aria-invalid={headerBlockers(headerText, "template-header").length > 0}
                      className="input"
                    />
                    <FieldMessages id="template-header-messages" note={notes.header} blockers={headerBlockers(headerText, "template-header")} />
                    {headerVars.length === 1 && (
                      <>
                        <SampleInputs
                          variables={[1]}
                          samples={{ 1: headerSample }}
                          onChange={(next) => setHeaderSample(next[1] ?? "")}
                          idPrefix="template-header-sample-"
                          label="Variable sample"
                          chipLabel={() => "Header {{1}}"}
                        />
                        <FieldMessages
                          id="template-header-sample-messages"
                          blockers={headerSample.trim() ? [] : blockers.header.filter((b) => b.fieldId === "template-header-sample-1")}
                        />
                      </>
                    )}
                  </div>
                )}

                {(headerType === "IMAGE" || headerType === "VIDEO" || headerType === "DOCUMENT") && (
                  <div className="mt-4">
                    {headerMediaUrl ? (
                      <div className="flex items-center justify-between rounded-xl border border-emerald-200 bg-emerald-50 p-3">
                        <span className="flex min-w-0 items-center gap-2">
                          <FileCode size={16} className="shrink-0 text-emerald-600" />
                          <span className="truncate text-[13px] font-medium text-emerald-800">{mediaPreview?.name ?? "File"} uploaded</span>
                        </span>
                        <button type="button" onClick={clearMedia} aria-label="Remove the file" className="rounded-lg p-1 text-emerald-600 hover:bg-emerald-100">
                          <X size={14} />
                        </button>
                      </div>
                    ) : (
                      <label className="flex cursor-pointer items-center gap-4 rounded-xl border-2 border-dashed border-[#d9d3c8] bg-[#fbfaf7] p-4 transition-colors hover:border-primary-300 hover:bg-primary-50/40">
                        <input
                          type="file"
                          accept={headerType === "IMAGE" ? "image/jpeg,image/png,image/webp" : headerType === "VIDEO" ? "video/mp4" : ".pdf,.doc,.docx"}
                          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleMediaUpload(f); }}
                          id="template-header-upload"
                          className="sr-only"
                        />
                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[#e7e2da] bg-white text-primary">
                          <Upload size={18} aria-hidden="true" />
                        </span>
                        <span>
                          <span className="block text-[13.5px] font-semibold text-ink">
                            {uploadingMedia ? "Uploading to Meta…" : `Upload the ${headerType.toLowerCase()} Meta shows the reviewer`}
                          </span>
                          <span className="block text-[12px] text-ink-muted">Up to 10 MB. You can send a different one with each message later.</span>
                        </span>
                      </label>
                    )}
                  </div>
                )}
              </>
            )}
          </Section>

          {/* 3. Message */}
          <Section
            n={3}
            title="Message"
            hint="required · up to 1,024 letters"
            done={!!bodyText.trim() && blockers.bodyRules.length === 0 && blockers.samples.length === 0}
            active
          >
            <VariableInserter
              label="Message text"
              value={bodyText}
              onChange={setBodyText}
              samples={bodySamples}
              onSamplesChange={setBodySamples}
              rows={5}
              maxLength={1024}
              placeholder="Write the message your customers will get…"
            />
            {!isAuth && (
              <div className="mt-3">
                <PlaceholderGuide
                  onUse={(body, samples) => {
                    setBodyText(body);
                    setBodySamples(samples);
                  }}
                />
              </div>
            )}
          </Section>

          {/* 4. Footer, 5. Buttons */}
          <Section n={4} title="Footer" hint="optional · small grey line" done={blockers.footer.length === 0}>
            <label htmlFor="template-footer" className="sr-only">Footer text</label>
            <input
              id="template-footer"
              value={footerText}
              onChange={(e) => {
                const cleaned = cleanFooter(e.target.value);
                show("footer", cleaned.note);
                setFooterText(cleaned.text);
              }}
              maxLength={60}
              placeholder="e.g. Demo Silks · reply STOP to stop"
              aria-describedby="template-footer-messages"
              aria-invalid={blockers.footer.length > 0}
              className="input"
            />
            <FieldMessages id="template-footer-messages" note={notes.footer} blockers={blockers.footer} />
          </Section>

          <Section
            n={5}
            title="Buttons"
            hint={isAuth ? "one Copy code or One-tap button" : "optional · up to 10"}
            done={blockers.btns.length === 0}
          >
            <ButtonBuilder buttons={buttons} onChange={setButtons} maxButtons={isAuth ? 1 : 10} disableCTA={false} />
          </Section>
        </div>

        {/* ── Right: live preview and Meta checks ── */}
        <aside className="min-w-0 space-y-4 xl:sticky xl:top-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-display text-base font-bold text-ink">Live preview</h2>
            <div className="flex rounded-xl border border-[#e2ddd5] bg-white p-0.5" role="group" aria-label="Preview">
              {[
                { on: true, label: "With sample" },
                { on: false, label: "With {{ }}" },
              ].map((m) => (
                <button
                  key={m.label}
                  type="button"
                  aria-pressed={previewWithSamples === m.on}
                  onClick={() => setPreviewWithSamples(m.on)}
                  className={`h-8 rounded-[10px] px-3 text-[12.5px] font-semibold transition ${
                    previewWithSamples === m.on ? "bg-[#0A1528] text-white" : "text-ink hover:bg-surface-subtle"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          <WhatsAppPreview
            headerType={headerType === "NONE" || headerType === "TEXT" ? undefined : headerType}
            headerText={headerType === "TEXT" ? headerText : undefined}
            headerMediaUrl={headerMediaUrl || undefined}
            headerMediaPreview={mediaPreview?.url}
            headerMediaName={mediaPreview?.name}
            bodyText={bodyText}
            bodySamples={previewWithSamples ? bodySamples : undefined}
            headerSample={previewWithSamples ? headerSample : undefined}
            footerText={footerText || undefined}
            buttons={buttons.map((b) => ({
              type: b.type,
              text: b.type === "ONE_TAP" ? (b.autofill_text || "Autofill") : b.text,
              url: b.url,
              phone: b.phone,
            }))}
          />

          <section className="rounded-2xl border border-[#e7e2da] bg-white p-4">
            <h3 className="mb-2.5 text-sm font-bold text-ink">Check before sending to Meta</h3>
            <ul className="grid gap-1.5 text-[12.5px] font-medium sm:grid-cols-2 xl:grid-cols-1">
              {checks.map((c) => (
                <li key={c.text} className={`flex items-center gap-1.5 ${c.ok ? "text-emerald-700" : "text-ink-muted"}`}>
                  {c.ok ? <Check size={13} strokeWidth={3} aria-hidden="true" /> : <span className="h-3 w-3 rounded-full border-[1.5px] border-current" aria-hidden="true" />}
                  {c.text}
                </li>
              ))}
            </ul>
          </section>
          <p className="text-[12.5px] leading-relaxed text-ink-muted">
            Templates are shared by all your numbers. After Meta approves one, you can use it in Chats, Reach, Auto-Messages and Commerce.
          </p>
        </aside>
      </div>

      {/* ── Sticky bottom bar ── */}
      <div className="sticky bottom-0 z-20 -mx-4 mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-[#e7e2da] bg-white/95 px-4 py-3 backdrop-blur md:-mx-6 md:px-6">
        {fixCount === 0 ? (
          <span className="flex items-center gap-1.5 text-[13px] font-semibold text-emerald-700">
            <Check size={14} strokeWidth={3} aria-hidden="true" /> Ready to send to Meta
          </span>
        ) : (
          <button type="button" onClick={() => focusFirst(blockers.all)} className="flex items-center gap-1.5 text-[13px] font-semibold text-amber-800 hover:underline">
            <AlertCircle size={14} aria-hidden="true" /> {fixCount === 1 ? blockers.all[0].message : `${fixCount} things to fix · show me`}
          </button>
        )}
        <div className="flex w-full items-center gap-2 sm:w-auto [&>button]:flex-1 sm:[&>button]:flex-none">
          {/* On a phone the "Back to Templates" link at the top is enough */}
          <Link href="/dashboard/templates" className="hidden h-11 items-center rounded-xl border border-[#ddd8cf] bg-white px-4 text-sm font-semibold text-ink hover:bg-surface-subtle sm:inline-flex">
            Back to Templates
          </Link>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={loading || !canManageTemplates}
            title={canManageTemplates ? "Submit template to WhatsApp" : "Read-only role: submit is disabled"}
            className="inline-flex h-11 items-center justify-center rounded-xl bg-primary px-5 text-sm font-bold text-white shadow-md transition hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? "Submitting…" : "Submit to Meta for approval"}
          </button>
        </div>
      </div>
    </div>
  );
}
