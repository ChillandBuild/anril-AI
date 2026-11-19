import { Fragment } from "react";
import Link from "next/link";
import { FileText, Link2 } from "lucide-react";
import ui from "./site.module.css";
import { DEMO_HREF, DEMO_LABEL } from "./content";
import { DemoSection } from "./DemoSection";
import { Faq } from "./Faq";
import type { ChatMsg, IndustryPage as Page } from "./industry-pages";
import { LeadsPreview } from "./LeadsPreview";
import { Eg, Frame, Kicker } from "./primitives";
import { JsonLd, breadcrumbSchema, faqSchema, serviceSchema } from "./schema";
import s from "./IndustryPage.module.css";

/** Chat text with any [placeholder] shown as a marked slot for the client's own details. */
function ChatText({ text }: { text: string }) {
  const parts = text.split(/\[([^\]]+)\]/);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <span key={i} className={s.ph} title="Filled in from your own business details">
            {p}
          </span>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

function Bubble({ m }: { m: ChatMsg }) {
  const side = m.from === "us" ? s.us : s.them;
  if (m.kind) {
    const Icon = m.kind === "file" ? FileText : Link2;
    return (
      <span className={`${s.bubble} ${side} ${s.att}`}>
        <Icon size={16} strokeWidth={2} aria-hidden="true" />
        {m.text}
      </span>
    );
  }
  return (
    <span className={`${s.bubble} ${side}`}>
      <ChatText text={m.text} />
    </span>
  );
}

/** One industry page: hero with a phone chat, quick answer, what people ask, three steps, features, dashboard, FAQ. */
export function IndustryPage({ page }: { page: Page }) {
  return (
    <Frame>
      <JsonLd data={faqSchema(page.faqs)} />
      <JsonLd data={serviceSchema(page)} />
      <JsonLd data={breadcrumbSchema([["Industries", "/industries"], [page.crumb, page.path]])} />

      <section className={`${ui.band} ${s.hero}`} aria-labelledby="page-h">
        <div className={s.heroText}>
          <Kicker>{page.label}</Kicker>
          <h1 id="page-h" className={s.title}>
            {page.h1}
          </h1>
          <p className={ui.lede}>{page.line}</p>
          <div className={s.cta}>
            <a className={ui.btn} href={DEMO_HREF}>
              {DEMO_LABEL}
            </a>
            <Link prefetch={false} className={`${ui.btn} ${ui.btnGhost}`} href="/pricing">
              See plans from ₹999 a month
            </Link>
          </div>
        </div>
        <div className={s.phoneWrap}>
          <div className={s.phone} role="img" aria-label={page.heroAlt}>
            <div className={s.phoneTop} aria-hidden="true">
              <span className={s.avatar}>A</span>
              <span>
                <b>Anril AI</b>
                <small>online</small>
              </span>
            </div>
            <div className={s.phoneChat} aria-hidden="true">
              {page.heroChat.map((m, i) => (
                <Bubble key={i} m={m} />
              ))}
              <span className={s.tag}>{page.heroTag}</span>
            </div>
          </div>
          <Eg>Example conversation</Eg>
        </div>
      </section>

      <section className={ui.band} aria-labelledby="qa-h">
        <div className={s.quick}>
          <h2 id="qa-h" className={ui.kicker}>
            Quick answer
          </h2>
          <p>{page.quickAnswer}</p>
        </div>
      </section>

      <section className={ui.band} aria-labelledby="asks-h" data-reveal>
        <Kicker>Enquiries</Kicker>
        <h2 className={ui.secH} id="asks-h">
          {page.asksH}
        </h2>
        <p className={ui.lede}>{page.asksIntro}</p>
        <ul className={s.asks}>
          {page.asks.map(([q, r], i) => (
            <li key={i}>
              <span className={s.who}>{q.who}</span>
              <Bubble m={q} />
              <Bubble m={r} />
            </li>
          ))}
        </ul>
        <Eg>Example conversations</Eg>
      </section>

      <section className={ui.band} aria-labelledby="how-h" data-reveal>
        <Kicker>How it works</Kicker>
        <h2 className={ui.secH} id="how-h">
          How Anril handles it
        </h2>
        <ol className={s.steps}>
          {page.steps.map(([name, text], i) => (
            <li key={name}>
              <span className={s.stepNo}>{String(i + 1).padStart(2, "0")}</span>
              <h3>{name}</h3>
              <p>{text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className={ui.band} aria-labelledby="get-h" data-reveal>
        <Kicker>Features</Kicker>
        <h2 className={ui.secH} id="get-h">
          What you get
        </h2>
        <ul className={s.gets}>
          {page.gets.map((g) => (
            <li key={g}>{g}</li>
          ))}
        </ul>
      </section>

      <section className={ui.band} aria-labelledby="shot-h" data-reveal>
        <Kicker>Dashboard</Kicker>
        <h2 className={ui.secH} id="shot-h">
          What your team sees
        </h2>
        <LeadsPreview rows={page.shot.rows} caption={page.shot.caption} alt={page.shot.alt} />
      </section>

      <section className={ui.band} id="faq" aria-labelledby="faq-h">
        <Kicker>FAQ</Kicker>
        <h2 className={ui.secH} id="faq-h">
          Questions people ask
        </h2>
        <Faq items={page.faqs.map((f) => ({ q: f.q, a: f.a }))} />
      </section>

      <section className={ui.band} aria-labelledby="rel-h">
        <h2 className={ui.secH} id="rel-h">
          Related
        </h2>
        <ul className={s.related}>
          {page.related.map((r) => (
            <li key={r.href}>
              <Link prefetch={false} href={r.href}>
                <b>{r.label}</b>
                <span>{r.note}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <DemoSection />
    </Frame>
  );
}
