import Link from "next/link";
import { Building2, Camera, Car, Factory, Globe, GraduationCap, Landmark, MessageCircle, MessagesSquare, Phone, Send, Sparkles, Stethoscope, type LucideIcon } from "lucide-react";
import ui from "./site.module.css";
import { CHANNELS, DEMO_HREF, DEMO_LABEL, INDUSTRIES, INDUSTRY_PAGE_PATHS } from "./content";
import { HOME_LEAD_ROWS, LeadsPreview } from "./LeadsPreview";
import { MarqueePause } from "./MarqueePause";
import { Eg, Kicker } from "./primitives";
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

// Facts about the product, not customer results. Words, not counts: "4 modules" and "3 lead marks"
// read like internal numbers (18 Nov 2026 brief).
const FACTS = [
  { big: "Hot · Warm · Cold", text: "Every lead marked Hot, Warm or Cold" },
  { big: "24/7", text: "AI replies to enquiries, including nights, weekends and holidays." },
  { big: "One inbox", text: "WhatsApp, Instagram, Facebook and Telegram in one inbox" },
] as const;

export function ProductFacts() {
  return (
    <section className={s.figs} aria-label="Anril AI at a glance">
      {FACTS.map(({ big, text }, i) => (
        <p key={text} data-reveal style={{ "--rd": `${i * 90}ms` } as React.CSSProperties}>
          <span className={`${s.big} ${big.length > 5 ? s.bigWords : ""}`}>{big}</span> {text}
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
      <p className={ui.lede}>Built for businesses in India and overseas that run on enquiries.</p>
      <Eg>Hover or tap a tile for an example conversation.</Eg>
      <ul className={s.tiles}>
        {INDUSTRIES.map((i, idx) => {
          const Icon = INDUSTRY_ICON[i.id] ?? Sparkles;
          return (
            <li key={i.id} data-reveal style={{ "--rd": `${idx * 60}ms` } as React.CSSProperties}>
              <Link prefetch={false} href={INDUSTRY_PAGE_PATHS[i.id]} className={s.tile}>
                <Icon size={22} strokeWidth={1.6} aria-hidden="true" />
                <span className={s.tname}>{i.name}</span>
                <span className={s.peek} aria-hidden="true">
                  <span>
                    <span className={s.q}>{i.example}</span>
                    <span className={s.r}>{i.reply}</span>
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

// Short descriptions of what each module does, plus the done-for-you service that feeds leads into it.
const HOME_MODULES = [
  { name: "Reach", text: "Bulk WhatsApp campaigns with approved templates, contact segments, scheduling and reports." },
  { name: "Engage", text: "AI replies in Tanglish or any language, Hot/Warm/Cold lead scoring, follow-ups and human handover." },
  { name: "Commerce", text: "Razorpay payment links, orders from chats, catalogue, stock alerts and dispatch status." },
  { name: "CallIQ", text: "Understands Tamil calls, records them and shows how each telecaller is performing." },
  { name: "Anril Attract", text: "A service: we run your Instagram and Facebook posts and Meta and Google ads, and the leads flow into Anril." },
] as const;

/** What the platform does, module by module, in the words people search for. */
export function HomeModules() {
  return (
    <section className={ui.band} id="modules" aria-labelledby="mod-h">
      <Kicker>Modules</Kicker>
      <h2 className={ui.secH} id="mod-h">WhatsApp campaigns, AI agent, payments and call tracking in one platform</h2>
      <p className={ui.lede}>
        Use one module or all of them. Every enquiry, payment and call lands in the same place.
      </p>
      <p className={s.modHint} aria-hidden="true">Swipe sideways to see each module →</p>
      <ul className={s.mods} role="region" aria-label="Modules" tabIndex={0}>
        {HOME_MODULES.map((m, i) => (
          <li key={m.name} data-reveal style={{ "--rd": `${i * 60}ms` } as React.CSSProperties}>
            <h3>{m.name}</h3>
            <p>{m.text}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

const PROOF = [
  { big: "1,800+", text: "enquiries answered every month" },
  { big: "6–7 months", text: "running every day, not a pilot" },
  { big: "24/7", text: "replies, including nights and Sundays" },
] as const;

/** Replaces the customer reviews: plain facts about our own use, with the case study behind them. */
export function BuiltOnEnquiries() {
  return (
    <section className={ui.band} id="proof" aria-labelledby="proof-h">
      <Kicker>Proof</Kicker>
      <h2 className={ui.secH} id="proof-h">Built and tested on real enquiries</h2>
      <p className={ui.lede}>
        A customer-facing business in our own group has used Anril for 6 to 7 months to answer customer enquiries.
      </p>
      <ul className={s.proof}>
        {PROOF.map((p, i) => (
          <li key={p.big} data-reveal style={{ "--rd": `${i * 80}ms` } as React.CSSProperties}>
            <b>{p.big}</b>
            <span>{p.text}</span>
          </li>
        ))}
      </ul>
      <Link prefetch={false} className={ui.tlink} href="/blog/case-study-customer-business-ai-replies">
        Read the case study
      </Link>
    </section>
  );
}

/** The lead list a team works from, right after the proof. Demo rows, never a client's data. */
export function TeamSees() {
  return (
    <section className={`${ui.band} ${s.sees}`} id="dashboard" aria-labelledby="sees-h">
      <div className={s.seesText}>
        <Kicker>Dashboard</Kicker>
        <h2 className={ui.secH} id="sees-h">What your team sees every day</h2>
        <p className={ui.lede}>
          Every enquiry from WhatsApp, Instagram and Facebook lands in one list. Hot leads sit at the top so your team
          calls them first.
        </p>
        <a className={ui.btn} href={DEMO_HREF}>
          {DEMO_LABEL}
        </a>
      </div>
      <LeadsPreview rows={HOME_LEAD_ROWS} alt="Anril dashboard lead list with enquiries from WhatsApp, Instagram, Facebook and Telegram, hot leads at the top" />
    </section>
  );
}
