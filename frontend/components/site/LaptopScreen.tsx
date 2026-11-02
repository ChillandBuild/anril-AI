import Image from "next/image";
import dashboard from "./images/hero-dashboard.png";
import s from "./HomeHero.module.css";

// The dashboard on the hero laptop is a screenshot laid over the photo, not part of the picture. It sits
// flat at 440 x 275 and is pinned to the photo's screen corners by the matrix3d in HomeHero.module.css
// (.screen). It is not `priority` and its sizes match its 440 px box: it is hidden on phones, and a priority
// preload there made phones download a 3840 px copy ahead of the real LCP photo.

/** Desktop and tablet only; phones get the portrait photo, where the screen is already large. */
export function LaptopScreen() {
  return (
    <div className={s.stage} aria-hidden="true">
      <div className={s.screen}>
        <Image className={s.shot} src={dashboard} alt="" width={440} quality={80} sizes="440px" />
        <div className={s.glare} />
      </div>
    </div>
  );
}
