import type { ReactNode } from "react";
import ui from "./site.module.css";
import s from "./PageIntro.module.css";

type Props = { title: string; lede: ReactNode; kicker?: string; children?: ReactNode };

/** The opening band of an inner page: the page's only h1, cleared below the fixed header. */
export function PageIntro({ title, lede, kicker, children }: Props) {
  return (
    <section className={`${ui.band} ${s.intro}`} aria-labelledby="page-h">
      {kicker && <span className={`${ui.kicker} ${ui.num}`}>{kicker}</span>}
      <h1 id="page-h" className={s.title}>{title}</h1>
      <p className={ui.lede}>{lede}</p>
      {children}
    </section>
  );
}
