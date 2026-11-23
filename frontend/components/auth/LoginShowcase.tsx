"use client";
import { useEffect, useMemo, useState } from "react";
import { AnrilLogo } from "@/components/logo";
import { LoginShaders } from "./LoginShaders";
import s from "./login.module.css";

type Who = "them" | "us";
type Enquiry = { channel: string; dot: string; msgs: [Who, string][]; end: string };

// Three made-up enquiries, one per channel, in the languages Anril replies in.
const ENQUIRIES: Enquiry[] = [
  {
    channel: "WhatsApp",
    dot: "var(--teal-l)",
    msgs: [
      ["them", "Fees evvalavu? Weekend batch irukka?"],
      ["us", "₹4,500 a month. Saturday and Sunday, 10 am. Shall I book a free demo class?"],
      ["them", "Ok, Saturday book pannunga."],
    ],
    end: "Hot lead sent to a telecaller with the full chat",
  },
  {
    channel: "Instagram",
    dot: "#E1306C",
    msgs: [
      ["them", "Is the 2BHK near OMR still available? Can I visit Sunday?"],
      ["us", "Yes, it is. Sunday 11 am or 4 pm. Which suits you?"],
      ["them", "4 pm."],
    ],
    end: "Site visit booked for Sunday, 4 pm",
  },
  {
    channel: "Facebook",
    dot: "#1877F2",
    msgs: [
      ["them", "Price for 50 pieces, delivery to Madurai?"],
      ["us", "₹180 each, so ₹9,000. Free delivery to Madurai in 3 days."],
      ["them", "Send the payment link."],
    ],
    end: "Payment link sent · ₹9,000",
  },
];

type Frame = { ms: number; shown: number; typing: boolean; hot: boolean; done: boolean; fade: boolean };

/** One enquiry as a list of frames: each message appears (Anril's after a typing bubble), then HOT, then the
 *  hand-off line, then everything fades before the next enquiry. */
function framesFor(e: Enquiry): Frame[] {
  const f: Frame[] = [{ ms: 400, shown: 0, typing: false, hot: false, done: false, fade: false }];
  e.msgs.forEach(([who], i) => {
    if (who === "us") f.push({ ms: 1100, shown: i, typing: true, hot: false, done: false, fade: false });
    f.push({ ms: who === "us" ? 900 : 1300, shown: i + 1, typing: false, hot: false, done: false, fade: false });
  });
  const n = e.msgs.length;
  f.push({ ms: 500, shown: n, typing: false, hot: true, done: false, fade: false });
  f.push({ ms: 3100, shown: n, typing: false, hot: true, done: true, fade: false });
  f.push({ ms: 500, shown: n, typing: false, hot: true, done: true, fade: true });
  return f;
}

/** The chat on the navy panel. Plays the enquiries in a loop; visitors who ask for reduced motion see the
 *  first one finished and still. Decorative, so hidden from assistive tech. */
function LiveChat() {
  const [k, setK] = useState(0);
  const [p, setP] = useState(0);
  const [still, setStill] = useState(false);
  const enquiry = ENQUIRIES[k];
  const frames = useMemo(() => framesFor(enquiry), [enquiry]);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setStill(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (still) return;
    const id = window.setTimeout(() => {
      if (p + 1 < frames.length) setP(p + 1);
      else {
        setP(0);
        setK((k + 1) % ENQUIRIES.length);
      }
    }, frames[p].ms);
    return () => window.clearTimeout(id);
  }, [still, p, k, frames]);

  const f: Frame = still ? { ms: 0, shown: enquiry.msgs.length, typing: false, hot: true, done: true, fade: false } : frames[p];

  return (
    <div className={`${s.chat} ${f.fade ? s.fade : ""}`} aria-hidden="true">
      <div className={s.chatTop}>
        <i className={s.chDot} style={{ background: enquiry.dot }} />
        {enquiry.channel}
        <span className={`${s.hot} ${f.hot ? s.on : ""}`}>HOT</span>
      </div>
      <div className={s.msgs}>
        {enquiry.msgs.slice(0, f.shown).map(([who, text]) => (
          <p key={`${k}-${text}`} className={`${s.bub} ${who === "us" ? s.us : s.them}`}>
            {text}
          </p>
        ))}
        {f.typing && (
          <p className={`${s.bub} ${s.us} ${s.typing}`}>
            <i />
            <i />
            <i />
          </p>
        )}
      </div>
      <div className={`${s.handoff} ${f.done ? s.on : ""}`}>
        <span>TC</span>
        {enquiry.end}
      </div>
      <div className={s.chatFoot}>
        <span>Example</span>
        <span className={s.steps}>
          {ENQUIRIES.map((e, i) => (
            <i key={e.channel} className={i === k ? s.on : ""} />
          ))}
        </span>
      </div>
    </div>
  );
}

/** The login page's navy side: logo, headline, what Anril does, and the live chat. On narrow screens it
 *  shrinks to a band with the logo and headline (CSS hides the rest, and the chat isn't mounted). */
export default function LoginShowcase() {
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const sync = () => setWide(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  return (
    <aside className={s.panel}>
      <LoginShaders variant="navy" />
      <AnrilLogo height={30} className="text-white" />
      <h2 className={s.title}>
        Every enquiry answered.
        <br />
        <em>Every hot lead called.</em>
      </h2>
      <div className={s.facts}>
        <span>Replies in ~4 s</span>
        <span>Tamil · Tanglish · English</span>
        <span>WhatsApp · Instagram · Facebook</span>
      </div>
      {wide && <LiveChat />}
      <div className={s.by}>
        A product from <b>Bloom Matrix</b>
      </div>
    </aside>
  );
}
