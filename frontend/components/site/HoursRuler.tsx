"use client";

import { useEffect, useRef } from "react";
import { loadScrollTrigger, prefersReducedMotion } from "./motion-lib";
import { Eg } from "./primitives";
import s from "./HoursRuler.module.css";

// Illustrative arrival times (hour of day) for one example day. Not real data,
// and labelled as such on the page.
const ARRIVALS = [0.6, 1.9, 6.8, 8.1, 9.2, 10.4, 11.3, 12.6, 13.4, 14.7, 15.5, 16.8, 18.1, 19.6, 20.4, 21.2, 21.9, 22.7, 23.4];
const OFFICE_START = 10;
const OFFICE_END = 19;
const isLate = (h: number) => h < OFFICE_START || h >= OFFICE_END;
const LATE_COUNT = ARRIVALS.filter(isLate).length;

const ramp = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};
/** 0 in the small hours, 1 through the working day, easing at dawn and dusk. */
const daylight = (h: number) => Math.min(ramp(5, 8, h), 1 - ramp(17, 20, h));

/**
 * A 24-hour ruler of enquiries arriving through an example day. As the section scrolls, a sweep line moves
 * from midnight to midnight: the sky darkens and brightens, each enquiry appears as it arrives, and the
 * counter tallies the ones that came in while the office was closed. Without motion it shows the whole day at once.
 */
export function HoursRuler() {
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap || prefersReducedMotion()) return;
    const marks = Array.from(wrap.querySelectorAll<HTMLElement>("[data-h]"));
    const count = wrap.querySelector<HTMLElement>("[data-count]");
    let cancelled = false;
    let kill = () => {};

    const apply = (p: number) => {
      const hour = p * 24;
      const light = daylight(hour);
      // Sun by day, moon by night: one disc riding an arc, brightest at its peak.
      const elev = Math.sin(Math.PI * (((hour + 18) % 24) / 12));
      wrap.style.setProperty("--p", String(p));
      wrap.style.setProperty("--night", String(1 - light));
      wrap.style.setProperty("--sy", String(86 - 62 * Math.abs(elev)));
      let late = 0;
      for (const m of marks) {
        const seen = Number(m.dataset.h) <= hour;
        m.toggleAttribute("data-seen", seen);
        if (seen && m.dataset.late === "") late += 1;
      }
      if (count) count.textContent = String(late);
    };

    wrap.dataset.live = "";
    apply(0);
    (async () => {
      try {
        const { ScrollTrigger } = await loadScrollTrigger();
        if (cancelled) return;
        const st = ScrollTrigger.create({ trigger: wrap, start: "top 88%", end: "bottom 38%", onUpdate: (self) => apply(self.progress) });
        apply(st.progress);
        kill = () => st.kill();
      } catch {
        // The scroll library did not load: show the whole day instead of an empty ruler.
        delete wrap.dataset.live;
        apply(1);
        wrap.style.setProperty("--night", "0");
      }
    })();
    return () => {
      cancelled = true;
      kill();
    };
  }, []);

  return (
    <div className={s.wrap} ref={wrapRef}>
      <p className={s.counter} aria-hidden="true">
        <b data-count>{LATE_COUNT}</b>
        <span>of {ARRIVALS.length} enquiries came in while the office was closed</span>
      </p>
      <div
        className={s.sky}
        role="img"
        aria-label={`Example day: ${ARRIVALS.length} enquiries arriving across 24 hours, ${LATE_COUNT} of them outside office hours`}
      >
        <i className={s.body} aria-hidden="true" />
        <div className={s.office} style={{ left: `${(OFFICE_START / 24) * 100}%`, width: `${((OFFICE_END - OFFICE_START) / 24) * 100}%` }}>
          <span>Office hours</span>
        </div>
        {ARRIVALS.map((h) => (
          <span
            key={h}
            className={isLate(h) ? `${s.mark} ${s.late}` : s.mark}
            style={{ left: `${(h / 24) * 100}%` }}
            data-h={h}
            data-late={isLate(h) ? "" : undefined}
          />
        ))}
        <div className={s.sweep} aria-hidden="true" />
      </div>
      <div className={s.hours} aria-hidden="true">
        <span>12 am</span><span>6 am</span><span>12 pm</span><span>6 pm</span><span>12 am</span>
      </div>
      <div className={s.legend}>
        <span><i />Enquiry during office hours</span>
        <span><i className={s.lateKey} />Enquiry after hours</span>
        <Eg>Example day, not real data</Eg>
      </div>
    </div>
  );
}
