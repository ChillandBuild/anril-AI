import Link from "next/link";
import { DEMO_HREF, DEMO_LABEL, INDUSTRIES, MORE_INDUSTRIES, industryPath } from "./content";
import card from "./FeatureRow.module.css";
import ui from "./site.module.css";
import s from "./IndustryGrid.module.css";

/** "D2C brands" stays as written; "Real estate" becomes "real estate". */
function inSentence(name: string): string {
  return /^[A-Z]{2}/.test(name) ? name : name.charAt(0).toLowerCase() + name.slice(1);
}

/** The 10 "Most popular" trades in an even grid, each with one example conversation that plays in as it scrolls into view. */
export function IndustryGrid() {
  return (
    <>
    <p className={s.hint} aria-hidden="true">Swipe sideways to see each industry →</p>
    <ul className={s.grid} aria-label="Most popular industries" tabIndex={0}>
      {INDUSTRIES.map((i, idx) => (
        <li key={i.id} id={i.id} className={s.cell} data-reveal style={{ "--rd": `${(idx % 2) * 90}ms` } as React.CSSProperties}>
          <h2 className={s.title}>{i.name}</h2>
          <p>People often ask about {i.asks.charAt(0).toLowerCase() + i.asks.slice(1)}</p>
          <div className={s.chat}>
            <div className={`${card.msg} ${card.in} ${s.b1}`}>
              {i.example}
              <small>Enquiry</small>
            </div>
            <div className={`${card.msg} ${card.out} ${s.b2}`}>
              {i.reply}
              <small>Anril AI</small>
            </div>
          </div>
          <p>{i.outcome}</p>
          <Link prefetch={false} className={ui.tlink} href={industryPath(i.id)}>
            More about {inSentence(i.name)} →
          </Link>
        </li>
      ))}
    </ul>
    </>
  );
}

/** The other 10 trades as small square cards, then the card for every other business. */
export function MoreIndustries() {
  return (
    <section className={ui.band} id="more" aria-labelledby="more-h">
      <h2 className={ui.secH} id="more-h">More businesses we work with</h2>
      <p className={ui.lede}>
        If your customers message before they buy, Anril replies in seconds, marks each lead Hot, Warm or Cold, and
        passes serious ones to your team.
      </p>
      <ul className={s.more}>
        {MORE_INDUSTRIES.map((i) => (
          <li key={i.id}>
            <Link prefetch={false} href={industryPath(i.id)} className={s.small}>
              <h3>{i.name}</h3>
              <p>{i.text}</p>
              <span className={s.go}>More about {inSentence(i.name)} →</span>
            </Link>
          </li>
        ))}
        <li className={s.any}>
          <div className={s.small}>
            <h3>Any business that runs on enquiries</h3>
            <p>If your customers ask before they buy, Anril can answer them. We&rsquo;ll show it on your own enquiries.</p>
            <a className={ui.tlink} href={DEMO_HREF}>
              {DEMO_LABEL}
            </a>
          </div>
        </li>
      </ul>
    </section>
  );
}
