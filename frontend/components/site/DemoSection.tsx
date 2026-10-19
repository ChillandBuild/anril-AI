import { DemoForm } from "./DemoForm";
import s from "./Demo.module.css";

/** The page close: a short promise on the left, the demo request form on the right. Every /new page ends here. */
export function DemoSection() {
  return (
    <section className={s.close} id="demo" aria-labelledby="demo-h">
      <div className={s.t} data-reveal>
        <div className={s.rule} />
        <h2 id="demo-h">See it working on your own enquiries</h2>
        <p>Tell us a little about your business and we will set up a demo.</p>
      </div>
      <DemoForm />
    </section>
  );
}
