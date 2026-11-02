import Link from "next/link";
import ui from "./site.module.css";
import { DEMO_HREF, DEMO_LABEL } from "./content";
import { DemoSection } from "./DemoSection";
import { Faq } from "./Faq";
import { ALL_LANDINGS, findLanding, type Landing } from "./landing-content";
import { PageIntro } from "./PageIntro";
import { Eg, Frame, Kicker } from "./primitives";
import { JsonLd, breadcrumbSchema, faqSchema } from "./schema";
import s from "./Landing.module.css";

/** One product or industry page: the answer under the H1, question headings, FAQs, related pages and the demo form. */
export function LandingPage({ page, parent }: { page: Landing; parent?: readonly [name: string, path: string] }) {
  const trail: [string, string][] = parent ? [[parent[0], parent[1]], [page.label, page.path]] : [[page.label, page.path]];
  const related = page.related.map((slug) => findLanding(ALL_LANDINGS, slug)).filter((l): l is Landing => Boolean(l));
  return (
    <Frame>
      <JsonLd data={breadcrumbSchema(trail)} />
      <JsonLd data={faqSchema(page.faqs)} />
      <PageIntro title={page.h1} lede={page.opening}>
        <div className={s.cta}>
          <a className={ui.btn} href={DEMO_HREF}>
            {DEMO_LABEL}
          </a>
          <Link prefetch={false} className={ui.tlink} href="/pricing">
            See plans from ₹999 a month
          </Link>
        </div>
      </PageIntro>

      {page.sections.map((sec, i) => (
        <section key={sec.h} className={ui.band} aria-labelledby={`sec-${i}`} data-reveal>
          {i === 0 && <Kicker>{page.kicker}</Kicker>}
          <h2 className={ui.secH} id={`sec-${i}`}>{sec.h}</h2>
          <div className={s.prose}>
            {sec.p.map((para) => (
              <p key={para.slice(0, 40)}>{para}</p>
            ))}
          </div>
          {i === 0 && page.example && (
            <>
              <div className={s.chat}>
                <span className={s.q}>{page.example.q}</span>
                <span className={s.r}>{page.example.r}</span>
              </div>
              <p className={s.outcome}>{page.example.outcome}</p>
              <Eg>Example conversation, not customer data</Eg>
            </>
          )}
        </section>
      ))}

      <section className={ui.band} id="faq" aria-labelledby="faq-h">
        <Kicker>FAQ</Kicker>
        <h2 className={ui.secH} id="faq-h">Questions about {page.label.toLowerCase()}</h2>
        <Faq items={page.faqs.map((f) => ({ q: f.q, a: f.a }))} />
      </section>

      <section className={ui.band} aria-labelledby="rel-h">
        <h2 className={ui.secH} id="rel-h">Related</h2>
        <ul className={s.related}>
          {related.map((r) => (
            <li key={r.slug}>
              <Link prefetch={false} href={r.path}>
                <b>{r.label}</b>
                <span>{r.opening.split(". ")[0]}.</span>
              </Link>
            </li>
          ))}
          <li>
            <Link prefetch={false} href="/pricing">
              <b>Plans and pricing</b>
              <span>Plans start from ₹999 a month (plus GST).</span>
            </Link>
          </li>
        </ul>
      </section>
      <DemoSection />
    </Frame>
  );
}
