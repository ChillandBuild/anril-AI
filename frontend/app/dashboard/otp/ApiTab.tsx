"use client";

import { CopyButton, StatusPill } from "./otpUi";
import { OTP_BASE, OtpDocs } from "./OtpDocs";
import { OtpKeysCard } from "./OtpKeysCard";

const STEPS = [
  {
    n: 1,
    title: "Create an API key",
    line: "Below, under API keys. Keep it on your server.",
    snippet: "Authorization: Bearer anr_otp_live_...",
    href: "#api-keys",
  },
  {
    n: 2,
    title: "Send a code",
    line: "Your server calls Anril to send a code to a phone.",
    snippet: "POST /send",
    href: "#send",
  },
  {
    n: 3,
    title: "Check the code",
    line: "When the customer has typed the code, your server checks it.",
    snippet: "POST /verify",
    href: "#verify",
  },
];

export function OtpApiTab() {
  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-[#e2e8f0] bg-white p-6 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
        <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#64748b]">Developers</p>
        <h2 className="mt-2 font-display text-2xl font-bold text-[#0A1528]">Anril OTP API</h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-[#64748b]">
          Send one-time codes by SMS or WhatsApp from your own server, and check the codes your customers type back.
        </p>

        <div className="mt-5">
          <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#64748b]">Base URL</p>
          <div className="mt-2 flex items-center gap-2">
            <code className="min-w-0 flex-1 break-all rounded-lg border border-[#e2e8f0] bg-[#f8fafc] px-3 py-2 font-mono text-sm text-[#0A1528]">
              {OTP_BASE}
            </code>
            <CopyButton text={OTP_BASE} className="shrink-0" />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <StatusPill tone="neutral">Auth: Bearer API key</StatusPill>
          <StatusPill tone="neutral">JSON over HTTPS</StatusPill>
        </div>
      </section>

      <div>
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.08em] text-[#64748b]">Quickstart</p>
        <ol className="grid gap-4 md:grid-cols-3">
          {STEPS.map((s) => (
            <li key={s.n}>
              <a
                href={s.href}
                className="block h-full rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-colors hover:border-[#cbd5e1] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
              >
                <span
                  aria-hidden="true"
                  className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-xs font-bold tabular-nums text-white"
                >
                  {s.n}
                </span>
                <p className="mt-3 text-sm font-bold text-[#0A1528]">{s.title}</p>
                <p className="mt-1 text-[13px] leading-5 text-[#64748b]">{s.line}</p>
                <code className="mt-3 block break-all rounded-lg bg-[#f8fafc] px-2.5 py-1.5 font-mono text-xs text-[#0A1528]">{s.snippet}</code>
              </a>
            </li>
          ))}
        </ol>
      </div>

      <div id="api-keys" className="scroll-mt-24">
        <OtpKeysCard />
      </div>

      <OtpDocs />
    </div>
  );
}
