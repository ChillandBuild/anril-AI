import Image from "next/image";
import Link from "next/link";
import ui from "./site.module.css";
import { HOURS, MAKER, OFFICE_LINE } from "./content";
import office1 from "./images/office-1.jpg";
import office2 from "./images/office-2.jpg";
import office3 from "./images/office-3.jpg";
import { Kicker } from "./primitives";
import s from "./AboutBlocks.module.css";

// Three commitments, each one a plain fact about how the product and this site behave.
const PRINCIPLES = [
  { line: "Answer fast.", text: "Every enquiry gets a reply when it arrives, including nights, weekends and holidays." },
  { line: "Show the hot lead.", text: "Every lead is marked hot, warm or cold, so your team calls the right person first." },
  { line: "Hand over to a person.", text: "When a customer needs a person, the conversation goes to your team with everything said so far." },
] as const;

export function Principles() {
  return (
    <section className={ui.band} aria-labelledby="pr-h">
      <Kicker>How we work</Kicker>
      <h2 className={ui.secH} id="pr-h">Three things we hold to</h2>
      <ol className={s.list}>
        {PRINCIPLES.map((p, i) => (
          <li key={p.line} data-reveal style={{ "--rd": `${i * 80}ms` } as React.CSSProperties}>
            <span className={s.line}>{p.line}</span>
            <p>{p.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Who makes Anril AI, with where to read more. */
export function MakerPanel() {
  return (
    <section className={ui.band} aria-labelledby="mk-h">
      <div className={s.maker} data-reveal>
        <div className={s.makerHead}>
          <span className={ui.kicker}>A product of</span>
          <h2 id="mk-h" className={s.makerName}>{MAKER.name}</h2>
        </div>
        <div className={s.makerBody}>
          <p>
            A business communication and sales growth platform. Four modules, Reach, Engage, CallIQ and Commerce, take a
            business from first message to final sale. Built for businesses in India and overseas.
          </p>
          <ul className={s.links}>
            <li>
              <a href={MAKER.href} rel="noopener">Visit {MAKER.name}</a>
            </li>
            <li>
              <Link prefetch={false} href="/pricing">See the four modules</Link>
            </li>
            <li>
              <Link prefetch={false} href="/industries">See examples by industry</Link>
            </li>
          </ul>
        </div>
      </div>
    </section>
  );
}

// Real photos of the Coimbatore office, where demos are held.
const OFFICE_PHOTOS = [
  { src: office1, alt: "The Anril AI team's workspace in Coimbatore: shared desks with computers and a sprint-plan whiteboard" },
  { src: office2, alt: "Bright workspace at the Anril AI office in Coimbatore with a green wall, shared desks and large windows" },
  { src: office3, alt: "Desks at the Anril AI office in Coimbatore with team value posters on the desk dividers" },
] as const;

/** Where the team works and where demos are held, with the address and opening hours. */
export function OfficePhotos() {
  return (
    <section className={ui.band} id="office" aria-labelledby="office-h">
      <Kicker>Our office</Kicker>
      <h2 className={ui.secH} id="office-h">Visit us in Coimbatore</h2>
      <p className={ui.lede}>
        Free demos are held at our office: {OFFICE_LINE}. Open {HOURS}, closed on government holidays.
      </p>
      <ul className={s.photos}>
        {OFFICE_PHOTOS.map((p, i) => (
          <li key={p.src.src} data-reveal style={{ "--rd": `${i * 80}ms` } as React.CSSProperties}>
            <Image src={p.src} alt={p.alt} sizes="(max-width: 760px) 100vw, 33vw" quality={75} />
          </li>
        ))}
      </ul>
    </section>
  );
}
