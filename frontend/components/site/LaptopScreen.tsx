import s from "./HomeHero.module.css";

// The dashboard on the hero laptop is real HTML laid over the photo, not part of the picture, so
// every letter stays sharp at any screen size. It is drawn flat at 440 x 275 and pinned to the
// photo's screen corners by the matrix3d in HomeHero.module.css (.screen). All numbers are example
// numbers for a made-up "Your Business" account, the same ones the photo showed.

const NAV = ["Dashboard", "Analytics", "Leads & Chats", "Conversations", "Segments"] as const;

const KPIS = [
  { label: "New leads today", value: "11", note: "From 11 channels", tone: "green" },
  { label: "New hot leads today", value: "4", note: "Fresh today", tone: "amber" },
  { label: "Conversions today", value: "0", note: "Nothing yet", tone: "teal" },
] as const;

const STATS = [
  { label: "AI auto-reply share", value: "60%", note: "31 AI · 21 Human" },
  { label: "Inbound today", value: "31" },
  { label: "Outbound today", value: "52" },
  { label: "Awaiting response", value: "0" },
  { label: "Escalations", value: "2", alert: true },
] as const;

/** Desktop and tablet only; phones get the portrait photo, where the screen is already large. */
export function LaptopScreen() {
  return (
    <div className={s.stage} aria-hidden="true">
      <div className={s.screen}>
        <aside className={s.side}>
          <b className={s.brand}>
            anril<i>AI</i>
          </b>
          <ul>
            {NAV.map((n, i) => (
              <li key={n} className={i === 0 ? s.on : undefined}>
                {n}
                {n === "Conversations" && <em>1</em>}
              </li>
            ))}
          </ul>
        </aside>
        <div className={s.main}>
          <header className={s.top}>
            <div>
              <b>Product Overview</b>
              <span>Here&apos;s what&apos;s happening with your leads.</span>
            </div>
            <div className={s.who}>
              <span className={s.clock}>4:26 pm</span>
              <span className={s.avatar}>A</span>
              <b>Your Business</b>
            </div>
          </header>
          <div className={s.kpis}>
            {KPIS.map((k) => (
              <div key={k.label} className={`${s.kpi} ${s[k.tone]}`}>
                <span>{k.label}</span>
                <b>{k.value}</b>
                <small>{k.note}</small>
              </div>
            ))}
          </div>
          <div className={s.panel}>
            <b>Is my AI carrying its weight?</b>
            <div className={s.stats}>
              {STATS.map((x) => (
                <div key={x.label} className={"alert" in x && x.alert ? s.alert : undefined}>
                  <span>{x.label}</span>
                  <b>{x.value}</b>
                  {"note" in x && <small>{x.note}</small>}
                </div>
              ))}
            </div>
          </div>
          <div className={s.pipe}>
            <b>Pipeline Activity</b>
            <span>11 leads categorised today</span>
            <i />
          </div>
        </div>
        <div className={s.glare} />
      </div>
    </div>
  );
}
