"use client";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  CornerUpLeft,
  Image as ImageIcon,
  Lock,
  Plus,
  Trash2,
  Video,
} from "lucide-react";
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
import FieldMessages, { SampleInputs, focusFirst, useFixNotes } from "../components/field-messages";
import Section, { ChecklistCard } from "../components/builder-section";
import { MAX_CARDS, MIN_CARDS, isComplete, moveCard, shapeProblems } from "../carousel-rules";

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

/** Meta's rules for one card; field ids are prefixed with the card so "show me" finds them. */
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

const isHttp = (u: string) => /^https?:\/\//i.test(u.trim());

/** The picture (or a soft placeholder) for a card tile and the preview. */
function CardMedia({ card, className }: { card: Card; className: string }) {
  const [failed, setFailed] = useState("");
  const url = card.header_media_url.trim();
  if (card.header_media_type === "IMAGE" && isHttp(url) && failed !== url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={url} alt="" loading="lazy" decoding="async" onError={() => setFailed(url)} className={`${className} object-cover`} />
    );
  }
  const Icon = card.header_media_type === "VIDEO" ? Video : ImageIcon;
  return (
    <div className={`${className} flex items-center justify-center ${card.header_media_type === "VIDEO" ? "bg-[#1f2c34] text-white/70" : "bg-[#e9edef] text-[#8696a0]"}`}>
      <Icon size={20} aria-hidden="true" />
    </div>
  );
}

export default function CarouselTemplateBuilderPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("en");
  const [bodyText, setBodyText] = useState("");
  const [bodySamples, setBodySamples] = useState<Record<number, string>>({});
  const { notes, show } = useFixNotes();
  const [cards, setCards] = useState<Card[]>([emptyCard(), emptyCard()]);
  const [active, setActive] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generatedName = toTemplateName(title);
  const doneCards = cards.filter(isComplete);
  const shape = shapeProblems(cards);
  const introBlockers = useMemo(() => {
    if (!bodyText.trim()) return [];
    const body = bodyBlockers(bodyText, "carousel-body").filter((b) => b.inline);
    return body.length ? body : sampleBlockers(bodyText, bodySamples, "carousel-body-sample-");
  }, [bodyText, bodySamples]);
  const perCard = useMemo(() => cards.map((c, i) => cardBlockers(c, i)), [cards]);

  // Everything that stops Submit, with where to look
  const allBlockers = useMemo(() => {
    const out: Blocker[] = [];
    if (!generatedName) out.push({ fieldId: "carousel-title", message: "Add a template title", inline: false });
    if (!bodyText.trim()) out.push({ fieldId: "carousel-body", message: "Write the intro message", inline: false });
    out.push(...introBlockers);
    perCard.forEach((b) => out.push(...b));
    if (doneCards.length < MIN_CARDS) out.push({ fieldId: "carousel-cards", message: `Finish at least ${MIN_CARDS} cards (a media link and text)`, inline: false });
    if (shape.media) out.push({ fieldId: "carousel-cards", message: "Use the same media type (all images or all videos) on every card", inline: false });
    if (shape.buttons) out.push({ fieldId: "carousel-cards", message: "Give every card the same buttons, in the same order", inline: false });
    return out;
  }, [generatedName, bodyText, introBlockers, perCard, doneCards.length, shape.media, shape.buttons]);

  const checks = [
    { ok: !!generatedName, text: "Title is fine" },
    { ok: !!bodyText.trim() && introBlockers.length === 0, text: "Intro message follows Meta's rules" },
    { ok: doneCards.length >= MIN_CARDS, text: `${doneCards.length} of ${cards.length} cards finished (2 to 10)` },
    { ok: doneCards.length >= MIN_CARDS && !shape.media, text: "Same media type on every card" },
    { ok: doneCards.length >= MIN_CARDS && !shape.buttons, text: "Same buttons on every card" },
    { ok: perCard.every((b) => b.length === 0), text: "Every {{ }} has a sample" },
  ];

  function updateCard(i: number, patch: Partial<Card>) {
    setCards((prev) => prev.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  }
  function addCard() {
    if (cards.length >= MAX_CARDS) return;
    // A new card copies the buttons and media type of the first, so the shape matches from the start
    const first = cards[0];
    const fresh = { ...emptyCard(), header_media_type: first?.header_media_type ?? "IMAGE", buttons: (first?.buttons ?? []).map((b) => ({ ...b })) };
    setCards((prev) => [...prev, fresh]);
    setActive(cards.length);
  }
  function removeCard(i: number) {
    if (cards.length <= MIN_CARDS) return;
    setCards((prev) => prev.filter((_, idx) => idx !== i));
    setActive((a) => Math.max(0, a >= i ? a - 1 : a));
  }
  function move(i: number, dir: -1 | 1) {
    setCards((prev) => moveCard(prev, i, dir));
    setActive(Math.min(Math.max(i + dir, 0), cards.length - 1));
  }
  function addButton(cardIdx: number, type: CardButton["type"]) {
    setCards((prev) => prev.map((c, idx) => {
      if (idx !== cardIdx || c.buttons.length >= 2) return c;
      return { ...c, buttons: [...c.buttons, type === "URL" ? { type, text: "", url: "" } : { type, text: "" }] };
    }));
  }
  function updateButton(cardIdx: number, btnIdx: number, patch: Partial<CardButton>) {
    setCards((prev) => prev.map((c, idx) => (idx !== cardIdx ? c : { ...c, buttons: c.buttons.map((b, bi) => (bi === btnIdx ? { ...b, ...patch } : b)) })));
  }
  function removeButton(cardIdx: number, btnIdx: number) {
    setCards((prev) => prev.map((c, idx) => (idx !== cardIdx ? c : { ...c, buttons: c.buttons.filter((_, bi) => bi !== btnIdx) })));
  }

  async function handleSubmit() {
    if (allBlockers.length) {
      const first = allBlockers[0];
      const m = first.fieldId.match(/^card-(\d+)-/);
      if (m) setActive(Number(m[1]));
      setTimeout(() => focusFirst(allBlockers), 30);
      return;
    }
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
          carousel_cards: doneCards.map((c) => ({
            header_media_type: c.header_media_type,
            header_media_url: c.header_media_url.trim(),
            body_text: c.body_text.trim(),
            body_examples: detectVariables(c.body_text).map((n) => (c.body_samples[n] ?? "").trim()),
            buttons: c.buttons.filter((b) => b.text.trim()).length > 0 ? c.buttons.filter((b) => b.text.trim()) : undefined,
          })),
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        let detail = text;
        try { detail = JSON.parse(text).detail ?? text; } catch { /* plain text */ }
        throw new Error(detail || "Submission failed");
      }
      router.push("/dashboard/templates");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submission failed");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setSubmitting(false);
    }
  }

  const card = cards[active] ?? cards[0];
  const i = cards[active] ? active : 0;
  const cardIssues = perCard[i] ?? [];
  const pill = (on: boolean) =>
    `inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-[13px] font-semibold transition ${
      on ? "border-primary bg-primary-50 text-primary-800 ring-2 ring-primary-100" : "border-[#e2ddd5] bg-white text-ink hover:border-primary-200"
    }`;

  return (
    <div className="w-full pb-28">

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        {/* ── Left: the whole carousel on one page ── */}
        <div className="min-w-0 space-y-4">
          {error && (
            <div className="flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <p>{error}</p>
            </div>
          )}

          {/* Title, type, language */}
          <section className="rounded-2xl border border-[#e7e2da] bg-white p-5 shadow-sm md:p-6">
            <div className="grid gap-4 md:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)]">
              <div className="min-w-0">
                <label htmlFor="carousel-title" className="mb-1.5 block text-[13px] font-semibold text-ink">Template title</label>
                <input id="carousel-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. New collection carousel" className="input" />
                <p className="mt-1.5 truncate text-[12px] text-ink-muted">
                  {generatedName ? (
                    <>Sent to Meta as <span className="rounded bg-surface-subtle px-1.5 py-0.5 font-mono font-semibold text-ink">{generatedName}</span></>
                  ) : (
                    "Small letters, numbers and _ only. We fix it as you type."
                  )}
                </p>
              </div>
              <div className="min-w-0">
                <span className="mb-1.5 block text-[13px] font-semibold text-ink">Type</span>
                <div className="flex h-10 items-center justify-between gap-2 rounded-[10px] border border-border bg-surface-subtle px-3.5 text-sm text-ink">
                  <span className="font-semibold">Marketing</span>
                  <Lock size={13} className="shrink-0 text-ink-muted" aria-hidden="true" />
                </div>
                <p className="mt-1.5 text-[12px] text-ink-muted">Always Marketing for carousels.</p>
              </div>
              <div className="min-w-0">
                <span className="mb-1.5 block text-[13px] font-semibold text-ink">Language</span>
                <Select aria-label="Language" value={language} onChange={setLanguage} options={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))} />
              </div>
            </div>
          </section>

          {/* 1. Intro message */}
          <Section n={1} title="Intro message" hint="shown above the cards" done={!!bodyText.trim() && introBlockers.length === 0}>
            <label htmlFor="carousel-body" className="sr-only">Intro message</label>
            <textarea
              id="carousel-body"
              value={bodyText}
              onChange={(e) => {
                const tidied = tidyVariables(e.target.value);
                show("intro", tidied.note);
                setBodyText(tidied.text);
              }}
              rows={2}
              placeholder="e.g. Vanakkam {{1}} 👋 Our new collection is here. Swipe to see more →"
              aria-describedby="carousel-body-messages"
              aria-invalid={introBlockers.some((b) => b.fieldId === "carousel-body")}
              className="input min-h-[72px] resize-y"
            />
            <FieldMessages id="carousel-body-messages" note={notes.intro} blockers={introBlockers.filter((b) => b.fieldId === "carousel-body")} />
            {!introBlockers.some((b) => b.fieldId === "carousel-body") && (
              <>
                <SampleInputs variables={detectVariables(bodyText)} samples={bodySamples} onChange={setBodySamples} idPrefix="carousel-body-sample-" />
                <FieldMessages id="carousel-body-sample-messages" blockers={introBlockers.filter((b) => b.fieldId.startsWith("carousel-body-sample-"))} />
              </>
            )}
          </Section>

          {/* 2. Cards */}
          <Section
            n={2}
            title="Cards"
            hint={`${cards.length} of ${MAX_CARDS}`}
            right="Every card: same media type and same buttons"
            done={doneCards.length >= MIN_CARDS && !shape.media && !shape.buttons && perCard.every((b) => b.length === 0)}
            active
          >
            {/* the card strip */}
            <div id="carousel-cards" tabIndex={-1} className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-2 outline-none">
              {cards.map((c, idx) => {
                const on = idx === i;
                const done = isComplete(c) && (perCard[idx] ?? []).length === 0;
                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => setActive(idx)}
                    aria-pressed={on}
                    aria-label={`Card ${idx + 1}`}
                    className={`w-40 shrink-0 overflow-hidden rounded-xl border bg-white text-left transition ${
                      on ? "border-primary ring-2 ring-primary-100" : "border-[#e2ddd5] hover:border-primary-200"
                    }`}
                  >
                    <div className="relative">
                      <CardMedia card={c} className="h-20 w-full" />
                      <span className="absolute left-1.5 top-1.5 rounded-md bg-black/55 px-1.5 py-0.5 text-[11px] font-bold text-white">{idx + 1}</span>
                      {done && (
                        <span className="absolute right-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500 text-white" aria-hidden="true">
                          <Check size={12} strokeWidth={3} />
                        </span>
                      )}
                    </div>
                    <p className={`truncate px-2.5 py-2 text-[12.5px] font-semibold ${c.body_text.trim() ? "text-ink" : "text-ink-muted"}`}>
                      {c.body_text.trim() || "Empty card"}
                    </p>
                  </button>
                );
              })}
              {cards.length < MAX_CARDS && (
                <button
                  type="button"
                  onClick={addCard}
                  className="flex w-32 shrink-0 flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed border-[#d9d3c8] text-[13px] font-semibold text-primary transition hover:border-primary-300 hover:bg-primary-50/40"
                >
                  <Plus size={18} aria-hidden="true" /> Add card
                </button>
              )}
            </div>
            {(shape.media || shape.buttons) && (
              <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-[12.5px] text-amber-900">
                {shape.media ? "Some cards use images and some use videos. " : ""}
                {shape.buttons ? "Cards have different buttons. " : ""}
                Meta needs every card to match.
              </p>
            )}

            {/* the selected card */}
            <div className="mt-4 rounded-2xl border border-[#ece7df] bg-[#fbfaf7] p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <p className="text-[13px] font-bold text-ink">Card {i + 1}</p>
                <div className="flex items-center gap-1">
                  <button type="button" onClick={() => move(i, -1)} disabled={i === 0} aria-label="Move card left" className="rounded-lg p-1.5 text-ink-muted hover:bg-white hover:text-ink disabled:opacity-30">
                    <ChevronLeft size={16} />
                  </button>
                  <button type="button" onClick={() => move(i, 1)} disabled={i === cards.length - 1} aria-label="Move card right" className="rounded-lg p-1.5 text-ink-muted hover:bg-white hover:text-ink disabled:opacity-30">
                    <ChevronRight size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={() => removeCard(i)}
                    disabled={cards.length <= MIN_CARDS}
                    title={cards.length <= MIN_CARDS ? "A carousel needs at least 2 cards" : "Remove this card"}
                    className="ml-1 inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-[12.5px] font-semibold text-ink-muted hover:bg-red-50 hover:text-red-600 disabled:opacity-30"
                  >
                    <Trash2 size={13} /> Remove
                  </button>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-[180px_minmax(0,1fr)]">
                {/* media */}
                <div className="min-w-0 space-y-2">
                  <div className="flex gap-1.5" role="radiogroup" aria-label="Media type">
                    {(["IMAGE", "VIDEO"] as const).map((t) => (
                      <button key={t} type="button" role="radio" aria-checked={card.header_media_type === t} onClick={() => updateCard(i, { header_media_type: t })} className={pill(card.header_media_type === t)}>
                        {t === "IMAGE" ? <ImageIcon size={13} aria-hidden="true" /> : <Video size={13} aria-hidden="true" />}
                        {t === "IMAGE" ? "Image" : "Video"}
                      </button>
                    ))}
                  </div>
                  <CardMedia card={card} className="h-28 w-full rounded-xl" />
                </div>

                {/* text, link, buttons */}
                <div className="min-w-0 space-y-3">
                  <div>
                    <label htmlFor={`card-${i}-media`} className="mb-1 block text-[12.5px] font-semibold text-ink">
                      {card.header_media_type === "IMAGE" ? "Image" : "Video"} link
                    </label>
                    <input
                      id={`card-${i}-media`}
                      value={card.header_media_url}
                      onChange={(e) => updateCard(i, { header_media_url: e.target.value })}
                      placeholder={card.header_media_type === "IMAGE" ? "https://… .jpg" : "https://… .mp4"}
                      className="input text-sm"
                    />
                    <p className="mt-1 text-[12px] text-ink-muted">Must open for anyone: Meta downloads it to approve.</p>
                  </div>

                  <div>
                    <label htmlFor={`card-${i}-body`} className="mb-1 block text-[12.5px] font-semibold text-ink">
                      Card text <span className="font-normal text-ink-muted">· e.g. product name and price</span>
                    </label>
                    <textarea
                      id={`card-${i}-body`}
                      value={card.body_text}
                      onChange={(e) => {
                        const tidied = tidyVariables(e.target.value);
                        show(`card-${i}`, tidied.note);
                        updateCard(i, { body_text: tidied.text });
                      }}
                      rows={2}
                      placeholder="e.g. Kanchi pattu · ₹8,900 · 6 colours"
                      aria-describedby={`card-${i}-body-messages`}
                      className="input min-h-[60px] resize-y text-sm"
                    />
                    <FieldMessages id={`card-${i}-body-messages`} note={notes[`card-${i}`]} blockers={cardIssues.filter((b) => b.fieldId === `card-${i}-body`)} />
                    {!cardIssues.some((b) => b.fieldId === `card-${i}-body`) && (
                      <>
                        <SampleInputs
                          variables={detectVariables(card.body_text)}
                          samples={card.body_samples}
                          onChange={(next) => updateCard(i, { body_samples: next })}
                          idPrefix={`card-${i}-body-sample-`}
                        />
                        <FieldMessages id={`card-${i}-body-sample-messages`} blockers={cardIssues.filter((b) => b.fieldId.startsWith(`card-${i}-body-sample-`))} />
                      </>
                    )}
                  </div>

                  <div>
                    <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                      <span className="text-[12.5px] font-semibold text-ink">
                        Buttons <span className="font-normal text-ink-muted">· up to 2, website or quick reply</span>
                      </span>
                      {card.buttons.length < 2 && (
                        <span className="flex gap-3">
                          <button type="button" onClick={() => addButton(i, "URL")} className="text-[12.5px] font-bold text-primary hover:underline">+ Website</button>
                          <button type="button" onClick={() => addButton(i, "QUICK_REPLY")} className="text-[12.5px] font-bold text-primary hover:underline">+ Quick reply</button>
                        </span>
                      )}
                    </div>
                    <div className="space-y-2">
                      {card.buttons.map((btn, bi) => (
                        <div key={bi}>
                          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-[#e7e2da] bg-white p-2 sm:flex-nowrap">
                            <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-primary-50 px-2 py-1 text-[11.5px] font-bold text-primary-800">
                              {btn.type === "URL" ? <ArrowUpRight size={12} aria-hidden="true" /> : <CornerUpLeft size={12} aria-hidden="true" />}
                              {btn.type === "URL" ? "Website" : "Reply"}
                            </span>
                            <input
                              id={`card-${i}-btn-label-${bi}`}
                              value={btn.text}
                              onChange={(e) => {
                                const cleaned = cleanButtonLabel(e.target.value);
                                show(`card-${i}-label-${bi}`, cleaned.note);
                                updateButton(i, bi, { text: cleaned.text.slice(0, 25) });
                              }}
                              placeholder="Button text"
                              aria-label={`Button ${bi + 1} text`}
                              maxLength={25}
                              className="min-w-0 flex-1 rounded-lg border border-border-subtle bg-white px-2.5 py-1.5 text-sm"
                            />
                            {btn.type === "URL" && (
                              <input
                                id={`card-${i}-btn-url-${bi}`}
                                value={btn.url || ""}
                                onChange={(e) => updateButton(i, bi, { url: e.target.value })}
                                onBlur={(e) => {
                                  const fixed = fixUrl(e.target.value);
                                  show(`card-${i}-url-${bi}`, fixed.note);
                                  if (fixed.text !== (btn.url || "")) updateButton(i, bi, { url: fixed.text });
                                }}
                                placeholder="https://…"
                                aria-label={`Button ${bi + 1} link`}
                                className="min-w-0 flex-[1.4] basis-full rounded-lg border border-border-subtle bg-white px-2.5 py-1.5 text-sm sm:basis-auto"
                              />
                            )}
                            <button type="button" onClick={() => removeButton(i, bi)} aria-label={`Remove button ${bi + 1}`} className="shrink-0 rounded-lg p-1.5 text-ink-muted hover:bg-red-50 hover:text-red-500">
                              <Trash2 size={13} />
                            </button>
                          </div>
                          <FieldMessages
                            id={`card-${i}-btn-${bi}-messages`}
                            note={notes[`card-${i}-label-${bi}`] ?? notes[`card-${i}-url-${bi}`]}
                            blockers={cardIssues.filter((b) => b.fieldId.startsWith(`card-${i}-btn-`) && (b.fieldId.endsWith(`-${bi}`) || b.fieldId === `card-${i}-btn-urlsample-${bi}-1`))}
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
              </div>
            </div>
          </Section>
        </div>

        {/* ── Right: live preview and checks ── */}
        <aside className="min-w-0 space-y-4 xl:sticky xl:top-4">
          <h2 className="font-display text-base font-bold text-ink">
            Live preview <span className="text-[12.5px] font-medium text-ink-muted">· swipe →</span>
          </h2>
          <div className="rounded-[28px] bg-[#0f1b2d] p-2.5 shadow-xl">
            <div className="overflow-hidden rounded-[20px] bg-[#EFE7DD]">
              <div className="flex items-center gap-2 bg-[#0a5c55] px-3.5 py-2.5 text-white">
                <span className="h-2 w-2 rounded-full bg-white" aria-hidden="true" />
                <span className="text-sm font-bold">Your business</span>
              </div>
              <div className="space-y-2 p-3">
                <div className="w-fit max-w-[90%] rounded-lg rounded-tl-[3px] bg-white px-3 py-2 shadow-[0_1px_0.5px_rgba(11,20,26,.13)]">
                  <p className="whitespace-pre-wrap text-[13px] text-[#111B21]">
                    {bodyText
                      ? bodyText.replace(/\{\{(\d+)\}\}/g, (m, n) => bodySamples[Number(n)]?.trim() || m)
                      : <span className="italic text-[#8696a0]">Intro message will appear here…</span>}
                  </p>
                  <p className="mt-0.5 text-right text-[10px] text-[#8696A0]">12:00 PM <span className="text-[#53bdeb]">✓✓</span></p>
                </div>
                <div className="-mx-3 flex gap-2 overflow-x-auto px-3 pb-1">
                  {cards.map((c, idx) => (
                    <div key={idx} className="w-44 shrink-0 overflow-hidden rounded-xl bg-white shadow-[0_1px_0.5px_rgba(11,20,26,.13)]">
                      <CardMedia card={c} className="h-28 w-full" />
                      <p className="line-clamp-2 min-h-[2.6em] px-2.5 pt-2 text-[12.5px] text-[#111B21]">
                        {c.body_text.replace(/\{\{(\d+)\}\}/g, (m, n) => c.body_samples[Number(n)]?.trim() || m) || <span className="italic text-[#8696a0]">Card text…</span>}
                      </p>
                      <div className="mt-1.5">
                        {c.buttons.filter((b) => b.text.trim()).map((b, bi) => (
                          <p key={bi} className="flex items-center justify-center gap-1 border-t border-[#eef0f1] py-1.5 text-[12.5px] font-medium text-[#027eb5]">
                            {b.type === "URL" ? <ArrowUpRight size={12} aria-hidden="true" /> : <CornerUpLeft size={11} aria-hidden="true" />}
                            {b.text}
                          </p>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
          <ChecklistCard checks={checks} title="Check" />
          <p className="text-[12.5px] leading-relaxed text-ink-muted">A carousel goes to Meta as one template. Customers swipe through 2 to 10 cards.</p>
        </aside>
      </div>

      {/* ── Sticky bottom bar ── */}
      <div className="sticky bottom-[calc(var(--mobile-nav-h)+env(safe-area-inset-bottom,0px))] lg:bottom-0 z-20 -mx-3 mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-[#e7e2da] bg-white/95 px-4 py-3 backdrop-blur sm:-mx-4 md:-mx-6 md:px-6">
        {allBlockers.length === 0 ? (
          <span className="flex items-center gap-1.5 text-[13px] font-semibold text-emerald-700">
            <Check size={14} strokeWidth={3} aria-hidden="true" /> Ready to send to Meta
          </span>
        ) : (
          <button type="button" onClick={handleSubmit} className="flex items-center gap-1.5 text-left text-[13px] font-semibold text-amber-800 hover:underline">
            <AlertCircle size={14} className="shrink-0" aria-hidden="true" /> {allBlockers.length === 1 ? allBlockers[0].message : `${allBlockers.length} things to fix · show me`}
          </button>
        )}
        <div className="flex w-full items-center gap-2 sm:w-auto [&>button]:flex-1 sm:[&>button]:flex-none">
          <Link
            href="/dashboard/templates"
            className="hidden md:inline-flex h-11 shrink-0 items-center justify-center gap-1.5 rounded-xl border border-[#ddd8cf] bg-white px-4 text-sm font-semibold text-ink transition hover:bg-surface-subtle"
          >
            <ArrowLeft size={15} aria-hidden="true" /> Back
          </Link>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="inline-flex h-11 items-center justify-center rounded-xl bg-primary px-5 text-sm font-bold text-white shadow-md transition hover:bg-primary/90 disabled:opacity-50"
          >
            {submitting ? "Submitting…" : "Submit to Meta for approval"}
          </button>
        </div>
      </div>
    </div>
  );
}
