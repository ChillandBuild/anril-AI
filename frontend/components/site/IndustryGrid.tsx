import { INDUSTRIES } from "./content";
import card from "./FeatureRow.module.css";
import { Eg } from "./primitives";
import s from "./IndustryGrid.module.css";

/** The six trades in an even grid, each with one example conversation that plays in as it scrolls into view. */
export function IndustryGrid() {
  return (
    <ul className={s.grid} aria-label="Industries">
      {INDUSTRIES.map((i, idx) => (
        <li key={i.id} id={i.id} className={s.cell} data-reveal style={{ "--rd": `${(idx % 3) * 90}ms` } as React.CSSProperties}>
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
          <Eg>Example conversation</Eg>
        </li>
      ))}
    </ul>
  );
}
