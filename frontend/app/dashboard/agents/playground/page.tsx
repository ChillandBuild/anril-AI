"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { MessageSquare, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { companionsApi, type CompanionModel, type PlaygroundDefaults } from "@/lib/api";
import { useCharacters } from "@/components/agents/CharacterSelect";
import { tabKeyDown } from "@/components/agents/PlaygroundParts";
import { PlaygroundChat } from "@/components/agents/PlaygroundChat";
import { PlaygroundSearch } from "@/components/agents/PlaygroundSearch";
import { PlaygroundSettings } from "@/components/agents/PlaygroundSettings";
import { DEFAULT_DISPLAY, FALLBACK_DEFAULTS, changedSettings, type ResultDisplay } from "@/components/agents/playground";
import { CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";

type Tab = "chat" | "search";
const TABS: { id: Tab; label: string; Icon: typeof Search }[] = [
  { id: "chat", label: "Chat", Icon: MessageSquare },
  { id: "search", label: "Search", Icon: Search },
];

/**
 * Chat with a character or search what it would find, with the knobs on the right.
 * Example: Maya on Chat, strictness moved to 0.60 -> every message is sent with
 * { memory_floor: 0.6 } and the row says "Live chat uses 0.70". Settings are shared by both tabs.
 */
export default function PlaygroundPage() {
  const { characters, selected, select, error } = useCharacters();
  const [tab, setTab] = useState<Tab>("chat");
  const [live, setLive] = useState<PlaygroundDefaults>(FALLBACK_DEFAULTS);
  const [settings, setSettings] = useState<PlaygroundDefaults>(FALLBACK_DEFAULTS);
  const [display, setDisplay] = useState<ResultDisplay>(DEFAULT_DISPLAY);
  const [models, setModels] = useState<CompanionModel[]>([]);
  const [liveModel, setLiveModel] = useState<string | null>(null);
  const [lastMessage, setLastMessage] = useState("");

  useEffect(() => {
    companionsApi
      .models()
      .then((r) => {
        setModels(r.models);
        setLiveModel(r.default);
        const defaults = r.playground_defaults;
        if (defaults) {
          setLive(defaults);
          // Follow live chat unless the owner already moved something before this arrived.
          setSettings((s) => (changedSettings(s, FALLBACK_DEFAULTS).length === 0 ? defaults : s));
        }
      })
      .catch(() => setModels([]));   // the model picker just hides; the fallback numbers stay
  }, []);

  const reset = () => {
    setSettings(live);
    setDisplay(DEFAULT_DISPLAY);
  };

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      {error ? (
        <ErrorNote message={error} />
      ) : characters === null ? (
        <LoadingRows />
      ) : characters.length === 0 || !selected ? (
        <div className={`${CARD} text-sm text-ink-secondary`}>
          Make a character first on <Link href="/dashboard/agents/characters" className="text-primary underline">Characters</Link>.
        </div>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
          <section className={cn(CARD, "p-[18px]")} aria-label="Playground">
            <div className="flex items-center justify-between gap-3">
              <div role="tablist" aria-label="Playground mode" className="inline-flex gap-1 rounded-[14px] border border-border p-1">
                {TABS.map(({ id, label, Icon }) => (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    id={`pg-tab-${id}`}
                    aria-selected={tab === id}
                    aria-controls={`pg-panel-${id}`}
                    tabIndex={tab === id ? 0 : -1}
                    onClick={() => setTab(id)}
                    onKeyDown={(e) => tabKeyDown(e, TABS.map((t) => t.id), tab, setTab)}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-[10px] px-3.5 py-1.5 text-sm",
                      tab === id ? "bg-primary/5 font-semibold text-primary shadow-sm" : "text-ink-secondary hover:text-ink",
                    )}
                  >
                    <Icon size={15} aria-hidden="true" /> {label}
                  </button>
                ))}
              </div>
              {tab === "chat" && <span className="text-[13px] text-ink-secondary">Testing as you</span>}
            </div>

            {/* Both stay mounted so switching tabs keeps the chat history. */}
            <div role="tabpanel" id="pg-panel-chat" aria-labelledby="pg-tab-chat" hidden={tab !== "chat"}>
              <PlaygroundChat
                character={selected}
                characters={characters}
                onSelectCharacter={select}
                settings={settings}
                live={live}
                models={models}
                liveModel={liveModel}
                onMessageSent={setLastMessage}
              />
            </div>
            <div role="tabpanel" id="pg-panel-search" aria-labelledby="pg-tab-search" hidden={tab !== "search"}>
              <PlaygroundSearch
                key={selected.id}
                character={selected}
                characters={characters}
                onSelectCharacter={select}
                settings={settings}
                live={live}
                display={display}
              />
            </div>
          </section>

          <PlaygroundSettings
            tab={tab}
            settings={settings}
            live={live}
            onChange={(patch) => setSettings((s) => ({ ...s, ...patch }))}
            display={display}
            onDisplay={(patch) => setDisplay((d) => ({ ...d, ...patch }))}
            onReset={reset}
            companionId={selected.id}
            lastMessage={lastMessage}
          />
        </div>
      )}
    </div>
  );
}
