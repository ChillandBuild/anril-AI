import ui from "./site.module.css";
import card from "./FeatureRow.module.css";
import { Eg, Kicker } from "./primitives";
import s from "./BeforeAfter.module.css";

/** The same late-night enquiry handled two ways. An illustration, labelled as one. */
export function BeforeAfter() {
  return (
    <section className={ui.band} id="difference" aria-labelledby="ba-h">
      <Kicker>The same enquiry</Kicker>
      <h2 className={ui.secH} id="ba-h">Without Anril AI, and with it</h2>
      <div className={s.pair}>
        <div className={s.side} data-reveal>
          <span className={s.label}>Without</span>
          <div className={`${card.msg} ${card.in}`}>
            Is the showroom open on Sunday?<small>11:42 pm · Enquiry</small>
          </div>
          <p>Nobody is at the desk. The enquiry waits until morning, with every other message that came in overnight.</p>
          <span className={s.tag}>Waiting</span>
        </div>
        <div className={`${s.side} ${s.with}`} data-reveal style={{ "--rd": "120ms" } as React.CSSProperties}>
          <span className={`${s.label} ${s.on}`}>With</span>
          <div className={`${card.msg} ${card.in}`}>
            Is the showroom open on Sunday?<small>11:42 pm · Enquiry</small>
          </div>
          <div className={`${card.msg} ${card.out}`}>
            Yes, 10 am to 7 pm. Would you like to book a test drive?<small>11:42 pm · Anril AI</small>
          </div>
          <p>The reply goes out when the enquiry arrives. The lead is marked hot and is near the top of the telecaller&apos;s list when the office opens.</p>
          <span className={`${s.tag} ${s.hot}`}>Hot · call first</span>
        </div>
      </div>
      <Eg>Illustration, not customer data.</Eg>
    </section>
  );
}
