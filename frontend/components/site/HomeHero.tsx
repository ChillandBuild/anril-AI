import { DEMO_HREF, DEMO_LABEL } from "./content";
import { HeroParallax } from "./HeroParallax";
import { HeroShaders } from "./HeroShaders";
import { HeroChannels, HeroInbox } from "./HeroInbox";
import s from "./HomeHero.module.css";

/**
 * Light hero: a drifting white and teal mesh with a teal halftone behind the copy, and an example customer
 * chat on a dark glass card. The page paints with a plain gradient first; HeroShaders animates it once idle.
 */
export function HomeHero() {
  return (
    <section className={s.hero} aria-labelledby="hero-h" data-hero>
      <div className={s.scene} data-hero-scene>
        <HeroShaders />
      </div>
      <div className={s.copy} data-hero-copy>
        <p className={s.langs}>
          <i aria-hidden="true" />
          Tamil, English and Tanglish
        </p>
        <h1 id="hero-h" className={s.title}>
          <span className={s.ln}>
            <span>Answer every enquiry.</span>
          </span>
          <span className={s.ln}>
            <span className={s.accent} style={{ animationDelay: "0.12s" }}>
              Call the right lead first.
            </span>
          </span>
        </h1>
        <p className={s.sub}>
          Anril AI replies to every WhatsApp, Instagram and Facebook enquiry in seconds, in Tamil, English or Tanglish.
          Scores leads and takes payments. From ₹999/month.
        </p>
        <div className={s.cta}>
          <a className={`${s.pill} ${s.dark}`} href={DEMO_HREF}>
            {DEMO_LABEL}
          </a>
          <a className={`${s.pill} ${s.ghost}`} href="#how">
            See how it works
          </a>
        </div>
      </div>
      <div className={s.right}>
        <HeroChannels />
        <HeroInbox />
      </div>
      <HeroParallax />
    </section>
  );
}
