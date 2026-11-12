import Link from "next/link";
import ui from "./site.module.css";
import { DEMO_HREF, DEMO_LABEL, SITE_URL } from "./content";
import { DemoSection } from "./DemoSection";
import { Faq } from "./Faq";
import { BLOG_AUTHOR, POSTS, postPath, type Post } from "./blog-posts";
import { PageIntro } from "./PageIntro";
import { Frame, Kicker } from "./primitives";
import { JsonLd, ORG_ID, breadcrumbSchema, faqSchema } from "./schema";
import s from "./Blog.module.css";

function fmt(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

export function BlogIndex() {
  return (
    <Frame>
      <JsonLd data={breadcrumbSchema([["Blog", "/blog"]])} />
      <PageIntro
        title="Anril AI blog"
        lede="Plain answers on WhatsApp chatbots, bulk WhatsApp messaging, lead scoring and telecalling for Indian businesses."
      />
      <section className={ui.band} aria-label="Articles">
        <ul className={s.list}>
          {POSTS.map((p) => (
            <li key={p.slug}>
              <Link prefetch={false} href={postPath(p.slug)} className={s.card}>
                <span className={s.meta}>{fmt(p.published)}</span>
                <h2>{p.title}</h2>
                <p>{p.description}</p>
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <DemoSection />
    </Frame>
  );
}

export function BlogArticle({ post }: { post: Post }) {
  const url = `${SITE_URL}${postPath(post.slug)}`;
  const article = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: post.title,
    description: post.description,
    mainEntityOfPage: url,
    datePublished: post.published,
    dateModified: post.updated,
    author: { "@type": "Organization", name: BLOG_AUTHOR, url: `${SITE_URL}/` },
    publisher: { "@id": ORG_ID },
  };
  const first = post.body[0];
  const rest = post.body.slice(1);
  return (
    <Frame>
      <JsonLd data={article} />
      <JsonLd data={faqSchema(post.faqs)} />
      <JsonLd data={breadcrumbSchema([["Blog", "/blog"], [post.title, postPath(post.slug)]])} />
      <PageIntro title={post.title} lede={first.type === "p" ? first.text : post.description}>
        <p className={s.meta}>
          By {post.author} · Published {fmt(post.published)} · Updated {fmt(post.updated)}
        </p>
      </PageIntro>
      <section className={ui.band} aria-label="Article">
        <div className={s.article}>
          {rest.map((b, i) =>
            b.type === "h2" ? (
              <h2 key={i}>{b.text}</h2>
            ) : b.type === "p" ? (
              <p key={i}>{b.text}</p>
            ) : b.type === "a" ? (
              <p key={i}>
                <Link prefetch={false} className={ui.tlink} href={b.href}>{b.label}</Link>
              </p>
            ) : b.type === "table" ? (
              <div key={i} className={s.tableWrap}>
                <table className={s.table}>
                  <thead>
                    <tr>{b.head.map((h, j) => <th key={j} scope="col">{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r) => (
                      <tr key={r[0]}>{r.map((c, j) => (j === 0 ? <th key={j} scope="row">{c}</th> : <td key={j}>{c}</td>))}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <ul key={i}>
                {b.items.map((it) => (
                  <li key={it}>{it}</li>
                ))}
              </ul>
            ),
          )}
        </div>
      </section>
      <section className={ui.band} id="faq" aria-labelledby="faq-h">
        <Kicker>FAQ</Kicker>
        <h2 className={ui.secH} id="faq-h">Questions on this topic</h2>
        <Faq items={post.faqs.map((f) => ({ q: f.q, a: f.a }))} />
      </section>
      <section className={ui.band} aria-labelledby="next-h">
        <h2 className={ui.secH} id="next-h">Put it into practice</h2>
        <div className={s.cta}>
          <Link prefetch={false} className={ui.tlink} href={post.link.href}>
            {post.link.label}
          </Link>
          <a className={ui.btn} href={DEMO_HREF}>
            {DEMO_LABEL}
          </a>
        </div>
      </section>
      <DemoSection />
    </Frame>
  );
}
