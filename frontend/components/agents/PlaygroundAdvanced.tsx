"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Companion, PlaygroundDefaults, PlaygroundSources } from "@/lib/api";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { PlaygroundSearch } from "@/components/agents/PlaygroundSearch";

const STORE_KEY = "pg-advanced-open";

function readOpen(): boolean {
  try {
    return window.localStorage.getItem(STORE_KEY) === "1";
  } catch {
    return false;   // blocked storage: closed
  }
}

const SOURCE_OPTIONS: { value: PlaygroundSources; label: string }[] = [
  { value: "all", label: "Files + memories" },
  { value: "knowledge", label: "Files only" },
  { value: "memories", label: "Memories only" },
];

/**
 * The closed "Advanced (for developers)" section under the chat. Only things that point to a fix
 * the owner can make. Example: Jothidar gave a wrong answer -> open it, pick "Files only" and the
 * next test message is answered from the files alone; "What Jothidar finds" shows which pages it
 * would read. Open or closed is remembered in this browser (localStorage "pg-advanced-open").
 */
export function PlaygroundAdvanced({
  character,
  live,
  sources,
  onSources,
}: {
  character: Companion;
  live: PlaygroundDefaults;
  sources: PlaygroundSources;
  onSources: (s: PlaygroundSources) => void;
}) {
  const [open, setOpen] = useState(false);   // closed until the browser says otherwise (no server/client mismatch)
  useEffect(() => setOpen(readOpen()), []);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    try {
      window.localStorage.setItem(STORE_KEY, next ? "1" : "0");
    } catch {
      /* blocked: it just won't be remembered */
    }
  };

  const name = character.name;
  return (
    <section className="mx-auto mt-6 max-w-[720px] rounded-[14px] border border-border px-4 py-3.5" aria-label="Advanced">
      <button
        type="button"
        id="pg-advanced-toggle"
        aria-expanded={open}
        aria-controls="pg-advanced-body"
        onClick={toggle}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <span>
          <span className="block text-[15px] font-semibold text-ink">
            Advanced <span className="font-normal text-ink-muted">(for developers)</span>
          </span>
          <span className="mt-0.5 block text-xs text-ink-muted">For finding out why a reply went wrong. Only changes this test chat.</span>
        </span>
        <ChevronDown size={18} aria-hidden="true" className={cn("shrink-0 text-ink-secondary transition-transform", open && "rotate-180")} />
      </button>

      {/* Hidden, not unmounted: a search you ran is still there when you open it again. */}
      <div id="pg-advanced-body" role="region" aria-labelledby="pg-advanced-toggle" hidden={!open} className="mt-3 divide-y divide-border-subtle border-t border-border-subtle">
        <div className="py-3.5">
          <h3 className="text-sm font-semibold text-ink">Answer from</h3>
          <p className="mb-2.5 mt-0.5 text-xs text-ink-muted">Narrow it down: did the wrong answer come from your files, or from what it remembers about you?</p>
          <SegmentedControl aria-label="Answer from" value={sources} onChange={onSources} options={SOURCE_OPTIONS} />
          {sources !== "all" && <p className="mt-1.5 text-xs text-ink-muted">Visitors always get files + memories.</p>}
        </div>

        <div className="py-3.5">
          <h3 className="text-sm font-semibold text-ink">What {name} finds</h3>
          <p className="mb-2.5 mt-0.5 text-xs text-ink-muted">Type a question to see which file pages and memories it would read, before it writes anything.</p>
          <PlaygroundSearch key={character.id} character={character} sources={sources} live={live} />
        </div>

        <div className="py-3.5">
          <h3 className="text-sm font-semibold text-ink">Put {name} on your website or app</h3>
          <p className="mt-0.5 text-xs text-ink-muted">
            The code, ready to copy, is on the{" "}
            <Link href="/dashboard/agents/install" className="text-primary hover:underline">
              Install page →
            </Link>
          </p>
        </div>
      </div>
    </section>
  );
}
