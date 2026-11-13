"use client";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Plus, Trash2, ArrowLeft, AlertCircle, Image as ImageIcon } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { LANGUAGES, detectVariables } from "../types";
import type { Button } from "../types";
import {
  bodyBlockers,
  buttonBlockers,
  cleanButtonLabel,
  fixUrl,
  sampleBlockers,
  tidyVariables,
} from "../template-rules";
import type { Blocker } from "../template-rules";
import FieldMessages, { BlockedReason, SampleInputs, focusFirst, useFixNotes } from "../components/field-messages";

type CardButton = {
  type: "QUICK_REPLY" | "URL";
  text: string;
  url?: string;
  url_example?: string;
};

type Card = {
  header_media_type: "IMAGE" | "VIDEO";
  header_media_url: string;
  body_text: string;
  body_samples: Record<number, string>;
  buttons: CardButton[];
};

const emptyCard = (): Card => ({
  header_media_type: "IMAGE",
  header_media_url: "",
  body_text: "",
  body_samples: {},
  buttons: [],
});

/** Meta's rules for one card; field ids are prefixed with the card so "Fix N things" finds them. */
function cardBlockers(card: Card, i: number): Blocker[] {
  if (!card.body_text.trim()) return [];
  const body = bodyBlockers(card.body_text, `card-${i}-body`).filter((b) => b.inline);
  const samples = body.length ? [] : sampleBlockers(card.body_text, card.body_samples, `card-${i}-body-sample-`);
  const buttons = buttonBlockers(card.buttons as Button[]).map((b) => ({
    ...b,
    fieldId: b.fieldId.replace("btn-", `card-${i}-btn-`),
  }));
  return [...body, ...samples, ...buttons];
}

function toTemplateName(title: string): string {
  return title.toLowerCase().replace(/[^a-z0-9\s_]/g, "").trim().replace(/\s+/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "");
}

export default function CarouselTemplateBuilderPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("en");
  const [bodyText, setBodyText] = useState("");
  const [bodySamples, setBodySamples] = useState<Record<number, string>>({});
  const { notes, show } = useFixNotes();
  const [cards, setCards] = useState<Card[]>([emptyCard(), emptyCard()]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generatedName = toTemplateName(title);
  const validCardCount = cards.filter(c => c.header_media_url.trim() && c.body_text.trim()).length;
  const introBlockers = useMemo(() => {
    if (!bodyText.trim()) return [];
    const body = bodyBlockers(bodyText, "carousel-body").filter((b) => b.inline);
    return body.length ? body : sampleBlockers(bodyText, bodySamples, "carousel-body-sample-");
  }, [bodyText, bodySamples]);
  const allBlockers = useMemo(
    () => [...introBlockers, ...cards.flatMap((c, i) => cardBlockers(c, i))],
    [introBlockers, cards],
  );
  const canSubmit =
    title.trim() && bodyText.trim() && validCardCount >= 2 && validCardCount <= 10 && allBlockers.length === 0;

  function updateCard(i: number, patch: Partial<Card>) {
    setCards(prev => prev.map((c, idx) => idx === i ? { ...c, ...patch } : c));
  }
  function addCard() {
    if (cards.length < 10) setCards(prev => [...prev, emptyCard()]);
  }
  function removeCard(i: number) {
    if (cards.length > 2) setCards(prev => prev.filter((_, idx) => idx !== i));
  }
  function addButton(cardIdx: number, type: CardButton["type"]) {
    setCards(prev => prev.map((c, idx) => {
      if (idx !== cardIdx) return c;
      if (c.buttons.length >= 2) return c;
      const newBtn: CardButton = type === "URL" ? { type, text: "", url: "" } : { type, text: "" };
      return { ...c, buttons: [...c.buttons, newBtn] };
    }));
  }
  function updateButton(cardIdx: number, btnIdx: number, patch: Partial<CardButton>) {
    setCards(prev => prev.map((c, idx) => {
      if (idx !== cardIdx) return c;
      return { ...c, buttons: c.buttons.map((b, bi) => bi === btnIdx ? { ...b, ...patch } : b) };
    }));
  }
  function removeButton(cardIdx: number, btnIdx: number) {
    setCards(prev => prev.map((c, idx) => {
      if (idx !== cardIdx) return c;
      return { ...c, buttons: c.buttons.filter((_, bi) => bi !== btnIdx) };
    }));
  }

  async function handleSubmit() {
    if (allBlockers.length) {
      focusFirst(allBlockers);
      return;
    }
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/templates/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify({
          name: generatedName,
          category: "MARKETING",
          language,
          body_text: bodyText.trim(),
          body_examples: detectVariables(bodyText).map((n) => (bodySamples[n] ?? "").trim()),
          carousel_cards: cards
            .filter(c => c.header_media_url.trim() && c.body_text.trim())
            .map(c => ({
              header_media_type: c.header_media_type,
              header_media_url: c.header_media_url.trim(),
              body_text: c.body_text.trim(),
              body_examples: detectVariables(c.body_text).map((n) => (c.body_samples[n] ?? "").trim()),
              buttons: c.buttons.filter(b => b.text.trim()).length > 0
                ? c.buttons.filter(b => b.text.trim())
                : undefined,
            })),
        }),
      });
      if (!res.ok) throw new Error(`Submission failed: ${await res.text()}`);
      router.push("/dashboard/templates");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <div className="mb-6">
        <Link
          href="/dashboard/templates"
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl hover:bg-[#f1f5f9] text-[#0A1528]/80 hover:text-[#0A1528] font-label text-sm font-semibold transition-all border border-[#e2e8f0] bg-transparent"
        >
          <ArrowLeft size={14} /> Back to Templates
        </Link>
      </div>

      {error && (
        <div className="mb-5 p-4 rounded-2xl bg-red-50 text-red-700 text-sm flex items-center gap-2">
          <AlertCircle size={16} />{error}
        </div>
      )}

      <div className="grid lg:grid-cols-[1fr_360px] gap-6">
        {/* Form */}
        <div className="space-y-5">
          <div className="card rounded-3xl p-5 space-y-4">
            <div>
              <label className="font-body text-sm font-medium text-ink mb-1.5 block">Template title</label>
              <input
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder="e.g. Summer Collection Launch"
                className="input"
              />
              {generatedName && (
                <p className="text-[11px] text-ink-muted mt-1.5">
                  Will submit as: <span className="font-mono text-ink bg-surface-subtle px-1.5 py-0.5 rounded">{generatedName}</span>
                </p>
              )}
            </div>
            <div>
              <label className="font-body text-sm font-medium text-ink mb-1.5 block">Language</label>
              <Select
                value={language}
                onChange={setLanguage}
                options={LANGUAGES.map((lang) => ({ value: lang.code, label: lang.label }))}
              />
            </div>
            <div>
              <label className="font-body text-sm font-medium text-ink mb-1.5 block">Intro message (shown above carousel)</label>
              <textarea
                id="carousel-body"
                value={bodyText}
                onChange={e => {
                  const tidied = tidyVariables(e.target.value);
                  show("intro", tidied.note);
                  setBodyText(tidied.text);
                }}
                rows={3}
                placeholder="Check out our new collection — swipe through to explore."
                aria-describedby="carousel-body-messages"
                aria-invalid={introBlockers.some((b) => b.fieldId === "carousel-body")}
                className="input resize-y min-h-[80px]"
              />
              <FieldMessages
                id="carousel-body-messages"
                note={notes.intro}
                blockers={introBlockers.filter((b) => b.fieldId === "carousel-body")}
              />
              {!introBlockers.some((b) => b.fieldId === "carousel-body") && (
                <>
                  <SampleInputs
                    variables={detectVariables(bodyText)}
                    samples={bodySamples}
                    onChange={setBodySamples}
                    idPrefix="carousel-body-sample-"
                  />
                  <FieldMessages
                    id="carousel-body-sample-messages"
                    blockers={introBlockers.filter((b) => b.fieldId.startsWith("carousel-body-sample-"))}
                  />
                </>
              )}
            </div>
          </div>

          {cards.map((card, i) => (
            <div key={i} className="card rounded-3xl p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-ink">Card {i + 1}</h3>
                {cards.length > 2 && (
                  <button onClick={() => removeCard(i)} className="p-1.5 rounded-lg hover:bg-red-50 text-ink-muted hover:text-red-500">
                    <Trash2 size={15} />
                  </button>
                )}
              </div>

              <div className="grid sm:grid-cols-[120px_1fr] gap-3 mb-4">
                <div>
                  <label className="text-xs text-ink-muted mb-1 block">Media type</label>
                  <Select
                    value={card.header_media_type}
                    onChange={v => updateCard(i, { header_media_type: v as "IMAGE" | "VIDEO" })}
                    options={[
                      { value: "IMAGE", label: "Image" },
                      { value: "VIDEO", label: "Video" },
                    ]}
                  />
                </div>
                <div>
                  <label className="text-xs text-ink-muted mb-1 block">Media URL (publicly hosted)</label>
                  <input
                    value={card.header_media_url}
                    onChange={e => updateCard(i, { header_media_url: e.target.value })}
                    placeholder="https://cdn.example.com/product.jpg"
                    className="input text-sm"
                  />
                </div>
              </div>

              <div className="mb-4">
                <label className="text-xs text-ink-muted mb-1 block">Card body text</label>
                <textarea
                  id={`card-${i}-body`}
                  value={card.body_text}
                  onChange={e => {
                    const tidied = tidyVariables(e.target.value);
                    show(`card-${i}`, tidied.note);
                    updateCard(i, { body_text: tidied.text });
                  }}
                  rows={2}
                  placeholder="Product name + short pitch"
                  aria-describedby={`card-${i}-body-messages`}
                  className="input text-sm resize-y min-h-[60px]"
                />
                <FieldMessages
                  id={`card-${i}-body-messages`}
                  note={notes[`card-${i}`]}
                  blockers={cardBlockers(card, i).filter((b) => b.fieldId === `card-${i}-body`)}
                />
                {!cardBlockers(card, i).some((b) => b.fieldId === `card-${i}-body`) && (
                  <>
                    <SampleInputs
                      variables={detectVariables(card.body_text)}
                      samples={card.body_samples}
                      onChange={(next) => updateCard(i, { body_samples: next })}
                      idPrefix={`card-${i}-body-sample-`}
                    />
                    <FieldMessages
                      id={`card-${i}-body-sample-messages`}
                      blockers={cardBlockers(card, i).filter((b) => b.fieldId.startsWith(`card-${i}-body-sample-`))}
                    />
                  </>
                )}
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs text-ink-muted">Buttons <span className="text-amber-600 font-medium">(max 2 · URL &amp; Quick Reply only)</span></label>
                  {card.buttons.length < 2 && (
                    <div className="flex gap-1">
                      <button
                        onClick={() => addButton(i, "URL")}
                        className="text-xs text-emerald-600 hover:text-emerald-700 px-2 py-1 rounded hover:bg-emerald-50"
                      >+ URL</button>
                      <button
                        onClick={() => addButton(i, "QUICK_REPLY")}
                        className="text-xs text-emerald-600 hover:text-emerald-700 px-2 py-1 rounded hover:bg-emerald-50"
                      >+ Reply</button>
                    </div>
                  )}
                </div>
                <p className="font-body text-xs text-amber-600 mb-2">Phone, Copy Code, and WhatsApp Call buttons are not supported in carousels by Meta.</p>
                <div className="space-y-2">
                  {card.buttons.map((btn, bi) => (
                    <div key={bi}>
                    <div className="flex items-center gap-2 p-2 rounded-xl bg-surface-subtle">
                      <span className="text-xs text-ink-muted px-2 font-medium">{btn.type === "URL" ? "URL" : "Reply"}</span>
                      <input
                        id={`card-${i}-btn-label-${bi}`}
                        value={btn.text}
                        onChange={e => {
                          const cleaned = cleanButtonLabel(e.target.value);
                          show(`card-${i}-label-${bi}`, cleaned.note);
                          updateButton(i, bi, { text: cleaned.text.slice(0, 25) });
                        }}
                        placeholder="Button text"
                        maxLength={25}
                        className="flex-1 px-2 py-1.5 rounded-lg text-sm bg-white border border-border-subtle"
                      />
                      {btn.type === "URL" && (
                        <input
                          id={`card-${i}-btn-url-${bi}`}
                          value={btn.url || ""}
                          onChange={e => updateButton(i, bi, { url: e.target.value })}
                          onBlur={e => {
                            const fixed = fixUrl(e.target.value);
                            show(`card-${i}-url-${bi}`, fixed.note);
                            if (fixed.text !== (btn.url || "")) updateButton(i, bi, { url: fixed.text });
                          }}
                          placeholder="https://..."
                          className="flex-[1.5] px-2 py-1.5 rounded-lg text-sm bg-white border border-border-subtle"
                        />
                      )}
                      <button onClick={() => removeButton(i, bi)} className="p-1 rounded hover:bg-red-50 text-ink-muted hover:text-red-500">
                        <Trash2 size={13} />
                      </button>
                    </div>
                    <FieldMessages
                      id={`card-${i}-btn-${bi}-messages`}
                      note={notes[`card-${i}-label-${bi}`] ?? notes[`card-${i}-url-${bi}`]}
                      blockers={cardBlockers(card, i).filter((b) => b.fieldId.startsWith(`card-${i}-btn-`) && (b.fieldId.endsWith(`-${bi}`) || b.fieldId === `card-${i}-btn-urlsample-${bi}-1`))}
                    />
                    {btn.type === "URL" && /\{\{\d+\}\}$/.test((btn.url || "").trim()) && (
                      <SampleInputs
                        variables={[1]}
                        samples={{ 1: btn.url_example ?? "" }}
                        onChange={(next) => updateButton(i, bi, { url_example: next[1] ?? "" })}
                        idPrefix={`card-${i}-btn-urlsample-${bi}-`}
                        label="Variable sample"
                        chipLabel={() => "Link {{1}}"}
                      />
                    )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}

          {cards.length < 10 && (
            <button onClick={addCard} className="w-full py-4 rounded-2xl border-2 border-dashed border-border-subtle text-sm text-ink-muted hover:border-emerald-300 hover:text-emerald-700 hover:bg-emerald-50/30 transition flex items-center justify-center gap-2">
              <Plus size={16} /> Add card ({cards.length} / 10)
            </button>
          )}

          <div className="flex gap-3 justify-end items-center flex-wrap pt-2">
            <BlockedReason blockers={allBlockers} />
            <Link href="/dashboard/templates" className="btn-ghost px-6">Cancel</Link>
            <button
              onClick={handleSubmit}
              disabled={!canSubmit || submitting}
              className="btn-primary px-8 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? "Submitting…" : "Submit to WhatsApp"}
            </button>
          </div>
        </div>

        {/* Preview */}
        <div className="lg:sticky lg:top-4 self-start">
          <p className="text-xs font-medium text-ink-muted mb-2">PREVIEW</p>
          <div className="bg-[#ECE5DD] rounded-2xl p-4 max-h-[80vh] overflow-y-auto">
            <div className="bg-white rounded-2xl rounded-tl-sm px-3 py-2 shadow-sm mb-2">
              <p className="text-[13px] text-[#111B21] whitespace-pre-wrap">
                {bodyText || <span className="text-gray-400 italic">Intro message will appear here…</span>}
              </p>
            </div>
            <div className="flex gap-2 overflow-x-auto pb-2 -mx-1 px-1">
              {cards.map((card, i) => (
                <div key={i} className="flex-shrink-0 w-44 bg-white rounded-xl shadow-sm overflow-hidden">
                  <div className="h-28 bg-gray-200 flex items-center justify-center overflow-hidden">
                    {card.header_media_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={card.header_media_url} alt={`Card ${i + 1}`} loading="lazy" decoding="async" className="w-full h-full object-cover" />
                    ) : (
                      <ImageIcon size={24} className="text-gray-400" />
                    )}
                  </div>
                  <div className="p-2.5">
                    <p className="text-[12px] text-[#111B21] line-clamp-3 min-h-[2.8em]">
                      {card.body_text || <span className="text-gray-400 italic">Body…</span>}
                    </p>
                    {card.buttons.filter(b => b.text.trim()).length > 0 && (
                      <div className="mt-2 space-y-1">
                        {card.buttons.filter(b => b.text.trim()).map((b, bi) => (
                          <div key={bi} className="text-[11px] text-emerald-700 text-center py-1 border-t border-gray-100">
                            {b.text}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-4 p-3 rounded-xl bg-amber-50 border border-amber-100 text-xs text-amber-800 leading-relaxed">
            Carousel templates need <strong>2–10 cards</strong>. Media URL must be publicly accessible (Meta downloads it during approval).
          </div>
        </div>
      </div>
    </div>
  );
}
