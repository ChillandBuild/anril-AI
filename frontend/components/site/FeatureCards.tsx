import type { CSSProperties } from "react";
import { Eg } from "./primitives";
import s from "./FeatureRow.module.css";

// The four illustrative cards from the mockup. Every one is marked as an example.

export function ChatCard() {
  return (
    <div className={`${s.card} ${s.chatloop}`}>
      <h3>WhatsApp</h3>
      <div className={`${s.msg} ${s.in}`}>Is the showroom open on Sunday?<small>Enquiry</small></div>
      <div className={`${s.msg} ${s.out}`}>Yes, 10 am to 7 pm. Would you like to book a test drive?<small>Anril AI</small></div>
      <div className={`${s.msg} ${s.in}`}>Yes please, around 4.<small>Enquiry</small></div>
      <Eg>Example</Eg>
    </div>
  );
}

export function ScoreCard() {
  return (
    <div className={s.card}>
      <h3>New lead</h3>
      <div className={s.sig}>Asked about fees</div>
      <div className={s.sig}>Wants a weekend batch</div>
      <div className={s.sig}>Asked to visit this week</div>
      <div className={s.scoreline}>
        <span className={s.marked}>Lead scored</span>
        <span className={s.chip}>HOT</span>
      </div>
      <Eg>Example</Eg>
    </div>
  );
}

export function RouteCard() {
  return (
    <div className={s.card}>
      <h3>Assigned just now</h3>
      <div className={`${s.li} ${s.first}`}>
        <div className={s.who}>
          <span className={s.av} aria-hidden="true">TC</span>
          <div><b>Telecaller</b><div><Eg>Next call</Eg></div></div>
        </div>
        <span className={s.chip}>HOT</span>
      </div>
      <div className={s.li}><span>Asked about</span><b>Course fees</b></div>
      <div className={s.li}><span>Channel</span><b>WhatsApp</b></div>
      <Eg>Example</Eg>
    </div>
  );
}

// 44 bars of a stylised waveform; every seventh run is the telecaller speaking.
const BARS = Array.from({ length: 44 }, (_, i) => ({
  h: 25 + Math.round(70 * Math.abs(Math.sin(i * 1.7) * Math.cos(i * 0.6))),
  d: -(i % 9) * 0.18,
  me: Math.floor(i / 7) % 2 === 1,
}));

export function CallCard() {
  return (
    <div className={s.card}>
      <h3>Call with telecaller · 4 min 12 s</h3>
      <div className={s.wave} aria-hidden="true">
        {BARS.map((b, i) => (
          <i
            key={i}
            className={b.me ? s.me : undefined}
            style={{ "--h": `${b.h}%`, "--d": `${b.d.toFixed(2)}s` } as CSSProperties}
          />
        ))}
      </div>
      <div className={s.li}>
        <span>
          <span className={s.leadKey}>Lead</span> and <span className={s.tcKey}>telecaller</span>
        </span>
        <span className={s.sc}>82 / 100</span>
      </div>
      <Eg>Example call</Eg>
    </div>
  );
}
