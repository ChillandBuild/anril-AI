"use client";
import { useEffect, useState } from "react";
import { api, type AutoMessageSummary } from "@/lib/api";

type State = { kind: "loading" } | { kind: "hidden" } | { kind: "empty" } | { kind: "counts"; counts: AutoMessageSummary };

const BOXES: { key: keyof AutoMessageSummary; label: string }[] = [
  { key: "sent", label: "sent" },
  { key: "failed", label: "failed" },
  { key: "skipped", label: "skipped" },
];

/** This month's sent / failed / skipped. A failed load hides the numbers rather than show a wrong one. */
export function HeaderCounts() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let live = true;
    api.autoMessages
      .summary()
      .then((counts) => {
        if (!live) return;
        const total = counts.sent + counts.failed + counts.skipped;
        setState(total === 0 ? { kind: "empty" } : { kind: "counts", counts });
      })
      .catch(() => live && setState({ kind: "hidden" }));
    return () => {
      live = false;
    };
  }, []);

  if (state.kind === "hidden") return null;
  if (state.kind === "empty") {
    return <p className="font-body text-xs text-ink-secondary">Nothing sent yet</p>;
  }
  return (
    <dl className="m-0 flex gap-2 max-sm:gap-1.5 max-sm:overflow-x-auto" aria-label="This month" aria-busy={state.kind === "loading"}>
      {BOXES.map((b) =>
        state.kind === "loading" ? (
          <div key={b.key} className="h-[58px] w-[72px] max-sm:h-8 max-sm:w-20 animate-pulse rounded-xl bg-border-subtle" />
        ) : (
          <div key={b.key} className="min-w-[72px] rounded-xl border border-border-subtle bg-white px-3 py-2 max-sm:flex max-sm:min-w-0 max-sm:shrink-0 max-sm:items-baseline max-sm:gap-1.5 max-sm:px-2.5 max-sm:py-1">
            <dd className="m-0 font-display text-lg font-bold leading-tight text-ink max-sm:text-base">{state.counts[b.key].toLocaleString("en-IN")}</dd>
            <dt className="font-body text-xs text-ink-secondary whitespace-nowrap">{b.label}</dt>
          </div>
        )
      )}
    </dl>
  );
}
