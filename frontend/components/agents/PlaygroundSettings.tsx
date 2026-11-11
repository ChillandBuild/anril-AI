"use client";
import { useId, useState } from "react";
import { Minus, Plus, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import { API_URL, type PlaygroundDefaults } from "@/lib/api";
import { CopyButton } from "@/components/agents/CodeBlock";
import { tabKeyDown } from "@/components/agents/PlaygroundParts";
import {
  REQUEST_LANGS,
  SEARCH_NO_API,
  SOURCE_LABEL,
  chatRequestSnippet,
  formatSetting,
  liveNote,
  stepValue,
  type RequestLang,
  type ResultDisplay,
} from "@/components/agents/playground";
import { CARD } from "@/components/agents/ui";

type Patch = Partial<PlaygroundDefaults>;

type Props = {
  tab: "chat" | "search";
  settings: PlaygroundDefaults;
  /** What live chat uses; a changed setting says so underneath. */
  live: PlaygroundDefaults;
  onChange: (patch: Patch) => void;
  display: ResultDisplay;
  onDisplay: (patch: Partial<ResultDisplay>) => void;
  onReset: () => void;
  companionId: string;
  /** The last message typed in Chat, shown in the REQUEST block. */
  lastMessage: string;
};

/**
 * The right card. Chat tab = "Memory settings", Search tab = "Search settings".
 * Example: Maya, strictness moved 0.70 -> 0.60: the row says "Live chat uses 0.70".
 */
export function PlaygroundSettings({ tab, settings, live, onChange, display, onDisplay, onReset, companionId, lastMessage }: Props) {
  const chat = tab === "chat";
  const note = (key: keyof PlaygroundDefaults) => liveNote(key, settings, live);

  return (
    <section className={cn(CARD, "space-y-1")} aria-label={chat ? "Memory settings" : "Search settings"}>
      <div className="flex items-center justify-between">
        <h2 className="text-[17px] font-semibold text-ink">{chat ? "Memory settings" : "Search settings"}</h2>
        <button type="button" onClick={onReset} className="inline-flex items-center gap-1 text-[13px] text-ink-secondary hover:text-ink">
          Reset <RotateCcw size={13} aria-hidden="true" />
        </button>
      </div>

      {chat && (
        <>
          <SectionLabel>MEMORY</SectionLabel>
          <Segmented
            label="Memory mode"
            value={settings.mode}
            options={[
              { value: "agentic", label: "Agentic" },
              { value: "auto", label: "Auto-search" },
            ]}
            onChange={(mode) => onChange({ mode })}
          />
          {note("mode") && <Note>{note("mode")}</Note>}
          <Row label="Use memory card" hint="The short summary of the person, always in the prompt" note={note("memory_card")}>
            <Toggle label="Use memory card" on={settings.memory_card} onChange={(memory_card) => onChange({ memory_card })} />
          </Row>
          <hr className="border-border" />
        </>
      )}

      <Row label="Sources" note={note("sources")} htmlFor="pg-sources">
        <select
          id="pg-sources"
          value={settings.sources}
          onChange={(e) => onChange({ sources: e.target.value as PlaygroundDefaults["sources"] })}
          className={DROPDOWN}
        >
          {(Object.keys(SOURCE_LABEL) as PlaygroundDefaults["sources"][]).map((s) => (
            <option key={s} value={s}>
              {SOURCE_LABEL[s]}
            </option>
          ))}
        </select>
      </Row>
      <hr className="border-border" />
      <Row label="Results" hint="Live: 5 memories, 3–4 passages" note={note("results")}>
        <Stepper label="Results" value={String(settings.results)} onStep={(d) => onChange({ results: stepValue(settings.results, d, 1, 20) })} step={1} />
      </Row>
      <Row label="Match strictness" hint="Memories: lowest meaning score kept" note={note("memory_floor")}>
        <Stepper
          label="Match strictness"
          value={formatSetting("memory_floor", settings.memory_floor)}
          onStep={(d) => onChange({ memory_floor: stepValue(settings.memory_floor, d, 0.3, 0.95) })}
          step={0.05}
        />
      </Row>
      <Row label="Judge minimum" hint="Knowledge: lowest judge score kept (0–3)" note={note("judge_min")}>
        <Stepper
          label="Judge minimum"
          value={formatSetting("judge_min", settings.judge_min)}
          onStep={(d) => onChange({ judge_min: stepValue(settings.judge_min, d, 0, 3) })}
          step={1}
        />
      </Row>
      <Row label="Rerank" note={note("rerank")} htmlFor="pg-rerank">
        <select
          id="pg-rerank"
          value={settings.rerank ? "judge" : "off"}
          onChange={(e) => onChange({ rerank: e.target.value === "judge" })}
          className={DROPDOWN}
        >
          <option value="judge">Judge (live)</option>
          <option value="off">Off</option>
        </select>
      </Row>
      <Row label="Rewrite query" note={note("rewrite")}>
        <Toggle label="Rewrite query" on={settings.rewrite} onChange={(rewrite) => onChange({ rewrite })} />
      </Row>
      <hr className="border-border" />

      {!chat && (
        <>
          <SectionLabel>INCLUDE IN RESULTS</SectionLabel>
          <div className="grid grid-cols-1 gap-2.5 py-1 sm:grid-cols-2">
            <label className="flex items-center gap-2 text-sm text-ink-muted" title="Our facts are not linked to each other yet">
              <input type="checkbox" disabled className={CHECKBOX} /> Related memories · later
            </label>
            <label className="flex items-center gap-2 text-sm text-ink">
              <input type="checkbox" checked={display.showDocs} onChange={(e) => onDisplay({ showDocs: e.target.checked })} className={CHECKBOX} />
              Source documents
            </label>
            <label className="flex items-center gap-2 text-sm text-ink">
              <input type="checkbox" checked={display.showDropped} onChange={(e) => onDisplay({ showDropped: e.target.checked })} className={CHECKBOX} />
              Dropped by judge
            </label>
          </div>
          <hr className="border-border" />
        </>
      )}

      <RequestBlock chat={chat} companionId={companionId} message={lastMessage} />

      <p className="pt-2 text-xs text-ink-muted">These settings only change this Playground, never live chat.</p>
    </section>
  );
}

const DROPDOWN =
  "rounded-[10px] border border-border bg-white px-2.5 py-1.5 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15";
const CHECKBOX = "h-4 w-4 accent-primary";

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="pb-2 pt-4 font-mono text-[11px] tracking-[0.08em] text-ink-secondary">{children}</div>;
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="mt-1 text-[11.5px] text-ink-muted">{children}</p>;
}

/** One setting: name (+ grey hint, + "Live chat uses ..." when changed) on the left, its control on the right. */
function Row({ label, hint, note, htmlFor, children }: { label: string; hint?: string; note?: string; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-11 items-center justify-between gap-3 py-1">
      <div className="min-w-0 text-sm text-ink">
        {htmlFor ? <label htmlFor={htmlFor}>{label}</label> : <span>{label}</span>}
        {hint && <small className="block text-[11.5px] text-ink-muted">{hint}</small>}
        {note && <small className="block text-[11.5px] text-ink-muted">{note}</small>}
      </div>
      {children}
    </div>
  );
}

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="grid grid-cols-2 rounded-xl border border-border p-[3px]">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-[9px] px-2 py-2 text-sm",
            value === o.value ? "bg-primary/5 font-semibold text-primary shadow-sm" : "text-ink-secondary hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Toggle({ label, on, onChange }: { label: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={cn("relative h-[22px] w-10 shrink-0 rounded-full transition-colors", on ? "bg-primary" : "bg-border")}
    >
      <span className={cn("absolute top-0.5 h-[18px] w-[18px] rounded-full bg-white shadow transition-all", on ? "left-5" : "left-0.5")} />
    </button>
  );
}

function Stepper({ label, value, step, onStep }: { label: string; value: string; step: number; onStep: (delta: number) => void }) {
  const btn = "grid h-8 w-8 place-items-center text-ink-secondary hover:bg-surface-mid hover:text-ink";
  return (
    <div role="group" aria-label={label} className="inline-flex shrink-0 overflow-hidden rounded-[10px] border border-border">
      <button type="button" aria-label={`Decrease ${label}`} onClick={() => onStep(-step)} className={btn}>
        <Minus size={14} aria-hidden="true" />
      </button>
      <span className="min-w-[52px] border-x border-border px-1 py-1 text-center font-mono text-[13px] leading-6 text-ink">
        {value}
      </span>
      <button type="button" aria-label={`Increase ${label}`} onClick={() => onStep(step)} className={btn}>
        <Plus size={14} aria-hidden="true" />
      </button>
    </div>
  );
}

/**
 * The real public call for this character: tabs for cURL / Python / TypeScript + Copy.
 * The Search tab has no public API, so it says that instead.
 */
function RequestBlock({ chat, companionId, message }: { chat: boolean; companionId: string; message: string }) {
  const [lang, setLang] = useState<RequestLang>("cURL");
  const tabsId = useId();
  const code = chat ? chatRequestSnippet(lang, { apiBase: API_URL, companionId, message }) : SEARCH_NO_API;
  return (
    <div>
      <div className="flex items-center justify-between py-2">
        <div className="font-mono text-[11px] tracking-[0.08em] text-ink-secondary">REQUEST</div>
        {chat && <CopyButton text={code} />}
      </div>
      <div className="overflow-hidden rounded-xl border border-border bg-surface-mid">
        {chat && (
          <div role="tablist" aria-label="Request language" className="flex gap-1 border-b border-border p-1">
            {REQUEST_LANGS.map((l) => (
              <button
                key={l}
                id={`${tabsId}-${l}`}
                type="button"
                role="tab"
                aria-selected={lang === l}
                tabIndex={lang === l ? 0 : -1}
                onClick={() => setLang(l)}
                onKeyDown={(e) => tabKeyDown(e, REQUEST_LANGS, lang, setLang)}
                className={cn(
                  "rounded-lg px-3 py-1 text-[13px]",
                  lang === l ? "bg-white font-semibold text-primary shadow-sm" : "text-ink-secondary hover:text-ink",
                )}
              >
                {l}
              </button>
            ))}
          </div>
        )}
        <pre
          role={chat ? "tabpanel" : undefined}
          aria-labelledby={chat ? `${tabsId}-${lang}` : undefined}
          className={cn("max-h-56 overflow-auto whitespace-pre-wrap break-words p-3 text-xs text-ink-secondary", chat && "font-mono")}
        >
          {code}
        </pre>
      </div>
    </div>
  );
}
