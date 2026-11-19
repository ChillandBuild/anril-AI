import type { LeadRow } from "./industry-pages";
import { Eg } from "./primitives";
import s from "./LeadsPreview.module.css";

/** Mixed trades, for the home page. Made-up names: never a real client's data. */
export const HOME_LEAD_ROWS: readonly LeadRow[] = [
  { name: "Kavya Raman", channel: "WhatsApp", note: "Campus visit on Saturday", score: "Hot", time: "2 min" },
  { name: "Senthil Kumar", channel: "Instagram", note: "2BHK · Sunday site visit", score: "Hot", time: "9 min" },
  { name: "Karthik Vel", channel: "WhatsApp", note: "Test drive on Saturday", score: "Hot", time: "16 min" },
  { name: "Meena Sundar", channel: "Facebook", note: "B.Com fee details", score: "Warm", time: "31 min" },
  { name: "Divya Mohan", channel: "Telegram", note: "Asked about timings", score: "Cold", time: "1 h" },
];

const SCORE_CLASS = { Hot: s.hot, Warm: s.warm, Cold: s.cold } as const;

function initials(name: string): string {
  return name
    .replace(/\(.*?\)/g, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
}

/**
 * The dashboard's lead list in a browser frame, drawn from demo rows (hot leads first).
 * It stands in for a screenshot and is marked as example data once, under the frame.
 */
export function LeadsPreview({ rows, caption, alt }: { rows: readonly LeadRow[]; caption?: string; alt: string }) {
  const hot = rows.filter((r) => r.score === "Hot").length;
  return (
    <figure className={s.fig}>
      <div className={s.browser} role="img" aria-label={alt}>
        <div className={s.bar} aria-hidden="true">
          <span className={s.dots}>
            <i />
            <i />
            <i />
          </span>
          <span className={s.url}>anrilaitech.com/dashboard/leads</span>
        </div>
        <div className={s.screen} aria-hidden="true">
          <div className={s.head}>
            <b>Leads</b>
            <span className={s.filters}>
              <span className={s.on}>All {rows.length}</span>
              <span>Hot {hot}</span>
              <span>Warm</span>
              <span>Cold</span>
            </span>
          </div>
          <ul className={s.rows}>
            {rows.map((r) => (
              <li key={r.name}>
                <span className={s.av}>{initials(r.name)}</span>
                <span className={s.who}>
                  <b>{r.name}</b>
                  <span>{r.note}</span>
                </span>
                <span className={s.ch}>{r.channel}</span>
                <span className={`${s.score} ${SCORE_CLASS[r.score]}`}>{r.score}</span>
                <span className={s.time}>{r.time}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <figcaption className={s.cap}>
        {caption && <span>{caption}</span>}
        <Eg>Example data, made-up names</Eg>
      </figcaption>
    </figure>
  );
}
