import Link from "next/link";
import { Building2, Camera, Car, Factory, Globe, GraduationCap, Landmark, MessageCircle, MessagesSquare, Phone, Send, Sparkles, Stethoscope, type LucideIcon } from "lucide-react";
import ui from "./site.module.css";
import { CHANNELS, INDUSTRIES } from "./content";
import { CountUp } from "./CountUp";
import { MarqueePause } from "./MarqueePause";
import { Kicker } from "./primitives";
import s from "./HomeBlocks.module.css";

// Plain stand-ins for each channel (not the brands' own logos).
const CHANNEL_ICON: Record<(typeof CHANNELS)[number], LucideIcon> = {
  WhatsApp: MessageCircle,
  Instagram: Camera,
  "Facebook Messenger": MessagesSquare,
  Telegram: Send,
  "Web chat": Globe,
  "Phone calls": Phone,
};

function ChannelItems() {
  return (
    <>
      {CHANNELS.map((c) => {
        const Icon = CHANNEL_ICON[c];
        return (
          <li key={c}>
            <span className={s.mark}>
              <Icon size={16} strokeWidth={2} aria-hidden="true" />
            </span>
            {c}
          </li>
        );
      })}
    </>
  );
}

/** The channels Anril AI answers on, as a slow marquee in place of a customer logo strip. */
export function ChannelStrip() {
  return (
    <section className={s.chans} aria-labelledby="chans-h">
      <div className={s.chansHead}>
        <h2 id="chans-h" className={s.chansH}>Works where your customers already message</h2>
        <MarqueePause />
      </div>
      <div className={s.marquee} data-marquee>
        <ul className={s.track}>
          <ChannelItems />
        </ul>
        {/* A second copy makes the loop seamless; screen readers skip it. */}
        <ul className={`${s.track} ${s.copy}`} aria-hidden="true">
          <ChannelItems />
        </ul>
      </div>
    </section>
  );
}

// Facts about the product, not customer results.
const FACTS = [
  { mark: 4, suffix: "", label: "4", text: "modules in one platform: Reach, Engage, CallIQ and Commerce." },
  { mark: 24, suffix: "/7", label: "24/7", text: "AI replies to enquiries, including nights, weekends and holidays." },
  { mark: 3, suffix: "", label: "3", text: "lead marks, hot, warm and cold, updated with every new message." },
] as const;

export function ProductFacts() {
  return (
    <section className={s.figs} aria-label="Anril AI at a glance">
      {FACTS.map(({ mark, suffix, label, text }, i) => (
        <p key={text} data-reveal style={{ "--rd": `${i * 90}ms` } as React.CSSProperties}>
          <span className={s.big}>
            <span aria-hidden="true">
              <CountUp to={mark} suffix={suffix} />
            </span>
            <span className={ui.sr}>{label}</span>
          </span>{" "}
          {text}
        </p>
      ))}
    </section>
  );
}

const INDUSTRY_ICON: Record<string, LucideIcon> = {
  education: GraduationCap,
  "real-estate": Building2,
  healthcare: Stethoscope,
  automotive: Car,
  manufacturing: Factory,
  "financial-services": Landmark,
};

/** Seven tiles; hovering or focusing one shows an example question and reply from that trade. */
export function IndustryList() {
  return (
    <section className={`${ui.band} ${s.ind}`} id="industries" aria-labelledby="ind-h">
      <Kicker>Industries</Kicker>
      <h2 className={ui.secH} id="ind-h">Built for businesses that run on enquiries</h2>
      <p className={ui.lede}>Businesses in India and overseas use Anril AI to answer every enquiry and call the right lead first.</p>
      <ul className={s.tiles}>
        {INDUSTRIES.map((i, idx) => {
          const Icon = INDUSTRY_ICON[i.id] ?? Sparkles;
          return (
            <li key={i.id} data-reveal style={{ "--rd": `${idx * 60}ms` } as React.CSSProperties}>
              <Link prefetch={false} href={`/industries#${i.id}`} className={s.tile}>
                <Icon size={22} strokeWidth={1.6} aria-hidden="true" />
                <span className={s.tname}>{i.name}</span>
                <span className={s.peek} aria-hidden="true">
                  <span>
                    <span className={s.q}>{i.example}</span>
                    <span className={s.r}>{i.reply}</span>
                    <small>Example conversation</small>
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
        <li data-reveal style={{ "--rd": `${INDUSTRIES.length * 60}ms` } as React.CSSProperties}>
          <Link prefetch={false} href="/industries#more" className={`${s.tile} ${s.more}`}>
            <Sparkles size={22} strokeWidth={1.6} aria-hidden="true" />
            <span className={s.tname}>Any business</span>
            <span className={s.peek} aria-hidden="true">
              <span>
                <span className={s.q}>Retail, travel, events, home services, hospitality</span>
                <span className={s.r}>If your customers ask before they buy, Anril AI answers them.</span>
              </span>
            </span>
          </Link>
        </li>
      </ul>
    </section>
  );
}
