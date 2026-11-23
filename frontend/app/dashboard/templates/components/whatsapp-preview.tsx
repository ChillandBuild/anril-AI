"use client";

import { useRef, useState } from "react";
import { FileText, Play, Phone, ExternalLink, Copy, MessageSquare, X } from "lucide-react";
import { formatSegments } from "../template-format";

type WhatsAppPreviewProps = {
  headerType?: 'NONE' | 'TEXT' | 'IMAGE' | 'VIDEO' | 'DOCUMENT';
  headerText?: string;
  headerMediaUrl?: string;
  /** Local copy of the chosen file (blob: URL) — Meta's upload handle can't be displayed. */
  headerMediaPreview?: string;
  headerMediaName?: string;
  bodyText: string;
  /** Sample values shown in place of {{n}}, the way Meta's reviewer reads them. */
  bodySamples?: Record<number, string>;
  headerSample?: string;
  footerText?: string;
  buttons?: Array<{ type: string; text: string; url?: string; phone?: string }>;
  carouselCards?: Array<{
    header_media_url?: string;
    body_text: string;
    buttons?: Array<{ type: string; text: string }>;
  }>;
};

/* ── helpers ─────────────────────────────────────────────────── */

function renderVariables(text: string, samples: Record<number, string> | undefined, keyPrefix: string) {
  const parts = text.split(/(\{\{\d+\}\})/g);
  return parts.map((part, i) =>
    /\{\{\d+\}\}/.test(part) ? (
      <span
        key={`${keyPrefix}${i}`}
        className="inline-flex items-center px-1.5 py-0.5 rounded-md text-xs font-semibold"
        style={{ background: "var(--primary-50)", color: "var(--primary-900)" }}
      >
        {samples?.[Number(part.slice(2, -2))]?.trim() || part}
      </span>
    ) : (
      <span key={`${keyPrefix}${i}`}>{part}</span>
    ),
  );
}

// *bold* and _italic_ show the way WhatsApp shows them; variables inside still show their sample.
function renderBody(text: string, samples?: Record<number, string>) {
  return formatSegments(text).map((seg, i) => {
    const inner = renderVariables(seg.text, samples, `${i}-`);
    if (seg.kind === "bold") return <strong key={i}>{inner}</strong>;
    if (seg.kind === "italic") return <em key={i}>{inner}</em>;
    return <span key={i}>{inner}</span>;
  });
}

function ButtonIcon({ type }: { type: string }) {
  const cls = "shrink-0";
  switch (type) {
    case "URL":
      return <ExternalLink size={13} className={cls} />;
    case "PHONE_NUMBER":
    case "WHATSAPP_CALL":
      return <Phone size={13} className={cls} />;
    case "COPY_CODE":
      return <Copy size={13} className={cls} />;
    case "QUICK_REPLY":
    default:
      return <MessageSquare size={13} className={cls} />;
  }
}

/* ── component ───────────────────────────────────────────────── */

export default function WhatsAppPreview({
  headerType = "NONE",
  headerText,
  headerMediaUrl,
  headerMediaPreview,
  headerMediaName,
  bodyText,
  bodySamples,
  headerSample,
  footerText,
  buttons,
  carouselCards,
}: WhatsAppPreviewProps) {
  const shownHeader = headerText && headerSample?.trim() ? headerText.replace(/\{\{1\}\}/, headerSample.trim()) : headerText;
  const carouselRef = useRef<HTMLDivElement>(null);
  const mediaSrc =
    headerMediaPreview || (headerMediaUrl && /^(https?:|blob:)/.test(headerMediaUrl) ? headerMediaUrl : undefined);

  const hasMedia = headerType !== "NONE" && headerType !== "TEXT";
  const [showAllOptions, setShowAllOptions] = useState(false);

  const visibleButtons = [...(buttons?.filter((b) => b.text.trim()) ?? [])].sort((a, b) => {
    const isCtaA = a.type !== "QUICK_REPLY";
    const isCtaB = b.type !== "QUICK_REPLY";
    if (isCtaA && !isCtaB) return -1;
    if (!isCtaA && isCtaB) return 1;
    return 0;
  });

  const ctas = visibleButtons.filter((b) => b.type !== "QUICK_REPLY");
  const qrs = visibleButtons.filter((b) => b.type === "QUICK_REPLY");

  return (
    <div className="flex flex-col items-center">
      {/* Phone bezel */}
      <div
        className="w-full max-w-[340px] rounded-[2rem] overflow-hidden shadow-xl"
        style={{ background: "#1F2C33", border: "6px solid #1F2C33" }}
      >
        {/* Notch */}
        <div className="flex justify-center pt-1.5 pb-1">
          <div
            className="w-24 h-[5px] rounded-full"
            style={{ background: "#2A3942" }}
          />
        </div>

        {/* WhatsApp header bar */}
        <div
          className="flex items-center gap-3 px-4 py-2.5"
          style={{ background: "var(--primary-950)" }}
        >
          <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center text-white text-xs font-bold">
            A
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-white text-sm font-semibold leading-tight truncate">
              Anril AI
            </p>
            <p className="text-white/60 text-[10px] leading-tight">online</p>
          </div>
        </div>

        {/* Chat area */}
        <div
          className="relative p-3 min-h-[380px] overflow-y-auto"
          style={{ background: "#ECE5DD" }}
        >
          {/* Subtle doodle pattern */}
          <div
            className="absolute inset-0 opacity-[0.04] pointer-events-none"
            style={{
              backgroundImage:
                "url('https://static.whatsapp.net/rsrc.php/v3/yl/r/r_Q1kFPEKdt.png')",
              backgroundSize: "400px",
            }}
          />

          <div className="relative z-10 space-y-1">
            {/* ── Message bubble ─────────────────────────── */}
            <div className="max-w-[92%]">
              {/* Media header */}
              {hasMedia && (
                <div className="rounded-t-lg overflow-hidden">
                  {headerType === "IMAGE" && (
                    mediaSrc ? (
                      /* eslint-disable-next-line @next/next/no-img-element */
                      <img
                        src={mediaSrc}
                        alt="Header"
                        loading="lazy"
                        decoding="async"
                        className="w-full h-36 object-cover bg-gray-200"
                      />
                    ) : (
                      <div className="w-full h-36 bg-gray-300 flex items-center justify-center">
                        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="m21 15-5-5L5 21" /></svg>
                      </div>
                    )
                  )}

                  {headerType === "VIDEO" && (
                    <div className="w-full h-36 bg-gray-800 flex items-center justify-center relative">
                      {mediaSrc && (
                        <video
                          src={mediaSrc}
                          muted
                          playsInline
                          preload="metadata"
                          className="absolute inset-0 w-full h-full object-cover opacity-70"
                        />
                      )}
                      <div className="relative w-12 h-12 rounded-full bg-white/90 flex items-center justify-center shadow-lg">
                        <Play size={20} className="text-gray-700 ml-0.5" fill="currentColor" />
                      </div>
                    </div>
                  )}

                  {headerType === "DOCUMENT" && (
                    <div className="w-full h-20 bg-gray-200 flex items-center justify-center gap-2">
                      <FileText size={22} className="text-gray-500" />
                      <span className="text-gray-500 text-xs font-medium truncate max-w-[80%]">
                        {headerMediaName || "document.pdf"}
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* Text bubble */}
              <div
                className={`bg-white px-3 py-2 shadow-sm ${
                  hasMedia ? "rounded-b-lg" : "rounded-lg rounded-tl-[4px]"
                }`}
              >
                {/* Text header */}
                {headerType === "TEXT" && headerText && (
                  <p className="text-sm font-bold mb-1" style={{ color: "#111B21" }}>
                    {shownHeader}
                  </p>
                )}
                {headerType !== "TEXT" && headerText && (
                  <p className="text-sm font-bold mb-1" style={{ color: "#111B21" }}>
                    {shownHeader}
                  </p>
                )}

                {/* Body */}
                <p
                  className="text-[13.5px] whitespace-pre-wrap break-words leading-relaxed"
                  style={{ color: "#111B21" }}
                >
                  {bodyText ? renderBody(bodyText, bodySamples) : (
                    <span className="text-gray-400 italic">
                      Your message will appear here…
                    </span>
                  )}
                </p>

                {/* Footer */}
                {footerText && (
                  <p
                    className="text-[11px] mt-2 pt-1.5"
                    style={{ color: "#8696A0", borderTop: "1px solid #f0f0f0" }}
                  >
                    {footerText}
                  </p>
                )}

                {/* Timestamp + ticks */}
                <div className="flex justify-end items-center gap-1 mt-0.5">
                  <span className="text-[10px]" style={{ color: "#8696A0" }}>
                    12:00 PM
                  </span>
                  <svg
                    viewBox="0 0 16 11"
                    height="11"
                    width="16"
                    className="text-[#53bdeb]"
                  >
                    <path
                      d="M11.832 0 4.887 6.945 1.79 3.848.376 5.263l4.511 4.511L13.246 1.414zM16 1.414l-1.414-1.414-3.414 3.414 1.414 1.414zM10.22 6.946l1.414-1.414 3.414 3.414-1.414 1.414z"
                      fill="currentColor"
                    />
                  </svg>
                </div>
              </div>

              {/* ── Buttons ──────────────────────────── */}
              {visibleButtons.length > 0 && (
                <div className="mt-1 rounded-lg overflow-hidden bg-white shadow-sm">
                  {visibleButtons.length > 3 ? (
                    <>
                      {visibleButtons.slice(0, 2).map((btn, i) => (
                        <div key={i}>
                          {i > 0 && (
                            <div className="h-px" style={{ background: "#E9EDEF" }} />
                          )}
                          <button
                            type="button"
                            className="w-full flex items-center justify-center gap-1.5 py-2.5 text-[13px] font-medium hover:bg-gray-50 transition-colors"
                            style={{ color: "#00A5F4" }}
                          >
                            <ButtonIcon type={btn.type} />
                            {btn.text}
                          </button>
                        </div>
                      ))}
                      <div className="h-px" style={{ background: "#E9EDEF" }} />
                      <button
                        type="button"
                        onClick={() => setShowAllOptions(true)}
                        className="w-full flex items-center justify-center gap-1.5 py-2.5 text-[13px] font-semibold hover:bg-gray-50 transition-colors"
                        style={{ color: "#00A5F4" }}
                      >
                        <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
                        </svg>
                        See all options
                      </button>
                    </>
                  ) : (
                    visibleButtons.map((btn, i) => (
                      <div key={i}>
                        {i > 0 && (
                          <div className="h-px" style={{ background: "#E9EDEF" }} />
                        )}
                        <button
                          type="button"
                          className="w-full flex items-center justify-center gap-1.5 py-2.5 text-[13px] font-medium hover:bg-gray-50 transition-colors"
                          style={{ color: "#00A5F4" }}
                        >
                          <ButtonIcon type={btn.type} />
                          {btn.text}
                        </button>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>

            {/* ── Carousel cards ──────────────────────── */}
            {carouselCards && carouselCards.length > 0 && (
              <div
                ref={carouselRef}
                className="flex gap-2 overflow-x-auto pb-2 mt-2 snap-x snap-mandatory scrollbar-none"
                style={{
                  scrollbarWidth: "none",
                  msOverflowStyle: "none",
                }}
              >
                {carouselCards.map((card, idx) => (
                  <div
                    key={idx}
                    className="snap-start shrink-0 w-[200px] rounded-lg overflow-hidden bg-white shadow-sm"
                  >
                    {card.header_media_url && (
                      /* eslint-disable-next-line @next/next/no-img-element */
                      <img
                        src={card.header_media_url}
                        alt={`Card ${idx + 1}`}
                        loading="lazy"
                        decoding="async"
                        className="w-full h-24 object-cover bg-gray-200"
                      />
                    )}
                    <div className="px-2.5 py-2">
                      <p
                        className="text-xs whitespace-pre-wrap break-words leading-relaxed line-clamp-4"
                        style={{ color: "#111B21" }}
                      >
                        {renderBody(card.body_text)}
                      </p>
                    </div>
                    {card.buttons && card.buttons.length > 0 && (
                      <div className="border-t" style={{ borderColor: "#E9EDEF" }}>
                        {card.buttons.map((btn, bi) => (
                          <div key={bi}>
                            {bi > 0 && (
                              <div
                                className="h-px"
                                style={{ background: "#E9EDEF" }}
                              />
                            )}
                            <div
                              className="flex items-center justify-center gap-1 py-2 text-[11px] font-medium"
                              style={{ color: "#00A5F4" }}
                            >
                              <ButtonIcon type={btn.type} />
                              {btn.text}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
          {/* See all options bottom sheet overlay */}
          <div
            className={`absolute inset-x-0 bottom-0 bg-white rounded-t-2xl shadow-2xl border-t border-gray-100 z-30 transition-all duration-300 ease-out transform ${
              showAllOptions ? "translate-y-0 opacity-100" : "translate-y-full opacity-0 pointer-events-none"
            }`}
          >
            <div className="w-10 h-1 bg-gray-300 rounded-full mx-auto my-2" />
            <div className="flex items-center justify-between px-4 pb-2 border-b border-gray-100">
              <button
                type="button"
                onClick={() => setShowAllOptions(false)}
                className="p-1 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600 transition-colors"
              >
                <X size={16} />
              </button>
              <span className="text-xs font-bold text-gray-700 uppercase tracking-wider">All options</span>
              <div className="w-6" />
            </div>
            
            <div className="p-3 space-y-1 max-h-[220px] overflow-y-auto">
              {ctas.map((btn, i) => (
                <button
                  key={`cta-${i}`}
                  type="button"
                  className="w-full flex items-center gap-3 py-2 px-3 text-left text-xs font-semibold text-sky-600 hover:bg-gray-50 rounded-xl transition-all"
                >
                  <ButtonIcon type={btn.type} />
                  {btn.text}
                </button>
              ))}
              {ctas.length > 0 && qrs.length > 0 && (
                <div className="h-px bg-gray-100 my-2" />
              )}
              {qrs.map((btn, i) => (
                <button
                  key={`qr-${i}`}
                  type="button"
                  className="w-full flex items-center gap-3 py-2 px-3 text-left text-xs font-semibold text-gray-700 hover:bg-gray-50 rounded-xl transition-all"
                >
                  <ButtonIcon type={btn.type} />
                  {btn.text}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Bottom bezel */}
        <div
          className="flex justify-center py-1.5"
          style={{ background: "#1F2C33" }}
        >
          <div
            className="w-28 h-1 rounded-full"
            style={{ background: "#2A3942" }}
          />
        </div>
      </div>
    </div>
  );
}
