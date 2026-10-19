import type { ReactNode } from "react";
import ui from "./site.module.css";
import { Kicker } from "./primitives";
import s from "./FeatureRow.module.css";

export type Feature = {
  id: string;
  kicker: string;
  title: string;
  body: string;
  wash: "teal" | "blue" | "beige";
  visual: ReactNode;
  /** Extra plain facts shown on the Product page. */
  points?: readonly string[];
};

type Props = { feature: Feature; flip: boolean; showPoints?: boolean; linkHref: string; linkLabel: string };

/** Text on one side, an illustrative card on a tinted panel on the other; alternates sides. */
export function FeatureRow({ feature, flip, showPoints = false, linkHref, linkLabel }: Props) {
  const titleId = `${feature.id}-h`;
  return (
    <section id={feature.id} className={`${s.row} ${flip ? s.flip : ""}`} aria-labelledby={titleId}>
      <div className={s.txt} data-reveal>
        <Kicker>{feature.kicker}</Kicker>
        <h2 id={titleId}>{feature.title}</h2>
        <p className={s.b}>{feature.body}</p>
        {showPoints && feature.points && (
          <ul className={s.points}>
            {feature.points.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        <a className={ui.tlink} href={linkHref}>
          {linkLabel}
        </a>
      </div>
      <div className={`${s.vis} ${s[feature.wash]}`} data-reveal style={{ "--rd": "120ms" } as React.CSSProperties}>
        {feature.visual}
      </div>
    </section>
  );
}
