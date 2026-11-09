import s from "./HomeHero.module.css";

const CHANNELS = [
  { name: "WhatsApp", color: "#25D366" },
  { name: "Instagram", color: "#E1306C" },
  { name: "Facebook", color: "#1877F2" },
  { name: "Telegram", color: "#29A9EB" },
];

/** The four channels Anril answers on, as small pills above the chat. */
export function HeroChannels() {
  return (
    <ul className={s.channels} aria-label="Channels">
      {CHANNELS.map((c) => (
        <li key={c.name}>
          <i style={{ background: c.color }} aria-hidden="true" />
          {c.name}
        </li>
      ))}
    </ul>
  );
}

/** An example customer chat on a dark glass card. Illustrative copy, labelled as an example, no real data. */
export function HeroInbox() {
  return (
    <div className={s.inboxWrap} aria-hidden="true">
      <div className={s.inbox}>
        <div className={s.inboxTop}>
          <span className={s.wa} />
          WhatsApp · example
          <b className={s.hot}>HOT</b>
        </div>
        <p className={`${s.bubble} ${s.them}`}>Is the showroom open on Sunday?</p>
        <p className={`${s.bubble} ${s.us}`}>Yes, 10 am to 7 pm. Would you like to book a test drive?</p>
        <p className={`${s.bubble} ${s.them} ${s.short}`}>Yes please, around 4.</p>
        <div className={s.assign}>
          <span>TC</span>
          Assigned to a telecaller, full chat on screen
        </div>
        <small className={s.note}>Example conversation, not real data</small>
      </div>
    </div>
  );
}
