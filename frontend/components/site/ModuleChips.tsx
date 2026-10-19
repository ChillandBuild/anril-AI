import { MODULES } from "./content";
import s from "./ModuleChips.module.css";

/** Four quick links under the Plans intro that jump to each module. */
export function ModuleChips() {
  return (
    <ul className={s.chips} aria-label="Jump to a module">
      {MODULES.map((mod, i) => (
        <li key={mod.id} data-reveal style={{ "--rd": `${i * 70}ms` } as React.CSSProperties}>
          <a href={`#${mod.id}`}>
            <span>0{i + 1}</span>
            {mod.name}
          </a>
        </li>
      ))}
    </ul>
  );
}
