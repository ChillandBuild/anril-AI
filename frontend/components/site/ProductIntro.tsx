import ui from "./site.module.css";
import card from "./FeatureRow.module.css";
import { Eg } from "./primitives";
import s from "./ProductIntro.module.css";

const TITLE = "From first message to the right call";
const LEDE =
  "Anril AI answers enquiries on WhatsApp, web chat and phone, marks every lead hot, warm or cold, sends the hot ones to a telecaller and scores the call that follows.";

/** Product page opener: the promise on the left, one enquiry playing out on the right (reply, score, handover). */
export function ProductIntro() {
  return (
    <section className={`${ui.band} ${s.intro}`} aria-labelledby="page-h">
      <div className={s.text}>
        <h1 id="page-h" className={s.title}>{TITLE}</h1>
        <p className={ui.lede}>{LEDE}</p>
      </div>
      <div className={s.frame} role="img" aria-label="An example enquiry: a customer asks about Sunday opening, Anril AI replies, the lead is marked hot and handed to a telecaller">
        <div className={`${card.card} ${s.window}`} aria-hidden="true">
          <h3>WhatsApp · example</h3>
          <div className={`${card.msg} ${card.in} ${s.step}`} style={{ "--i": 0 } as React.CSSProperties}>
            Is the showroom open on Sunday?<small>Enquiry</small>
          </div>
          <div className={`${card.msg} ${card.out} ${s.step}`} style={{ "--i": 1 } as React.CSSProperties}>
            Yes, 10 am to 7 pm. Would you like to book a test drive?<small>Anril AI</small>
          </div>
          <div className={`${card.msg} ${card.in} ${s.step}`} style={{ "--i": 2 } as React.CSSProperties}>
            Yes please, around 4.<small>Enquiry</small>
          </div>
          <div className={`${s.row} ${s.step}`} style={{ "--i": 3 } as React.CSSProperties}>
            <span className={card.marked}>Lead scored</span>
            <span className={card.chip}>HOT</span>
          </div>
          <div className={`${s.row} ${s.step}`} style={{ "--i": 4 } as React.CSSProperties}>
            <span className={card.who}><span className={card.av}>TC</span><b>Assigned to a telecaller</b></span>
          </div>
          <Eg>Example, not real data</Eg>
        </div>
      </div>
    </section>
  );
}
