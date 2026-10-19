import { getImageProps } from "next/image";
import { DEMO_HREF, DEMO_LABEL } from "./content";
import { HeroParallax } from "./HeroParallax";
import { LaptopScreen } from "./LaptopScreen";
import desktopPhoto from "./images/hero-desktop.jpg";
import mobilePhoto from "./images/hero-mobile.jpg";
import s from "./HomeHero.module.css";

// On desktop the laptop screen is HTML laid over the photo (LaptopScreen), so its text is crisp at any
// size. Phones get the portrait crop, where the screen already fills the width. Example numbers only.
const ALT = "A laptop on a sunlit desk showing the Anril AI dashboard, with a hand on the keyboard";

/** The whole photo at its own 16:9 shape (portrait crop on phones), with copy on its darker left side. */
export function HomeHero() {
  // q75: about 96 KB AVIF on desktop, 68 KB on phones.
  const common = { alt: ALT, sizes: "100vw", quality: 75, priority: true } as const;
  const { props: { srcSet: mobileSrcSet } } = getImageProps({ ...common, src: mobilePhoto });
  const { props: desktopImg } = getImageProps({ ...common, src: desktopPhoto });

  return (
    <section className={s.hero} aria-labelledby="hero-h" data-hero>
      <div className={s.scene} data-hero-scene>
        <div className={s.zoom}>
          <picture>
            <source media="(max-width: 700px)" srcSet={mobileSrcSet} sizes="100vw" />
            {/* eslint-disable-next-line @next/next/no-img-element -- art-directed <picture> built from getImageProps */}
            <img {...desktopImg} alt={ALT} className={s.photo} />
          </picture>
          <LaptopScreen />
        </div>
      </div>
      <div className={s.copy} data-hero-copy>
        <h1 id="hero-h" className={s.title}>
          <span className={s.ln}>
            <span>Answer every enquiry.</span>
          </span>
          <span className={s.ln}>
            <span style={{ animationDelay: "0.12s" }}>Call the right lead first.</span>
          </span>
        </h1>
        <p className={s.sub}>
          Anril AI answers every enquiry on WhatsApp, web chat and phone, shows you which leads are ready to buy, and
          gets your telecallers calling them first.
        </p>
        <div className={s.cta}>
          <a className={`${s.pill} ${s.white}`} href={DEMO_HREF}>
            {DEMO_LABEL}
          </a>
          <a className={`${s.pill} ${s.grey}`} href="#how">
            See how it works
          </a>
        </div>
      </div>
      <HeroParallax />
    </section>
  );
}
