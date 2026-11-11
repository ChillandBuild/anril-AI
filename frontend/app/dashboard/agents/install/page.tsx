"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { companionsApi, type CompanionInstall } from "@/lib/api";
import { CharacterSelect, useCharacters } from "@/components/agents/CharacterSelect";
import { CodeBlock, CopyButton } from "@/components/agents/CodeBlock";
import { installPrompt } from "@/components/agents/installPrompt";
import { CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";

const SERVER_TABS = [
  { id: "python", label: "Python" },
  { id: "node", label: "Node" },
  { id: "curl", label: "curl (your own chat screen)" },
] as const;

/** Copy-paste install for one character: an AI prompt, the widget tags and the server code. */
export default function InstallPage() {
  const { characters, selected, select, error: listError } = useCharacters();
  const [info, setInfo] = useState<CompanionInstall | null>(null);
  const [error, setError] = useState("");
  const [server, setServer] = useState<(typeof SERVER_TABS)[number]["id"]>("python");

  useEffect(() => {
    if (!selected) return;
    let alive = true;
    setInfo(null);
    setError("");
    companionsApi
      .install(selected.id)
      .then((r) => alive && setInfo(r))
      .catch((e: Error) => alive && setError(e.message || "Could not load the install code."));
    return () => {
      alive = false;
    };
  }, [selected]);

  if (listError) return <div className="w-full p-4 sm:p-6"><ErrorNote message={listError} /></div>;
  if (characters === null) return <div className="w-full p-4 sm:p-6"><LoadingRows /></div>;
  if (characters.length === 0) {
    return (
      <div className="w-full p-4 sm:p-6">
        <div className={`${CARD} text-sm text-ink-secondary`}>
          Make a character first on <Link href="/dashboard/agents/characters" className="text-primary underline">Characters</Link>.
        </div>
      </div>
    );
  }

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      <CharacterSelect characters={characters} value={selected?.id ?? ""} onChange={select} />

      {error && <ErrorNote message={error} />}
      {!info && !error && <LoadingRows rows={4} />}

      {info && selected && (
        <>
          {!info.has_active_key && (
            <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              Create a key first on <Link href="/dashboard/agents/keys" className="font-medium underline">API Keys</Link>. The code below reads it from ANRIL_COMPANION_KEY.
            </div>
          )}
          {info.status !== "live" && (
            <p className="text-sm text-ink-secondary">
              {selected.name} is {info.status}. Set it Live on its character page before customers can chat.
            </p>
          )}

          <section className={`${CARD} space-y-2`} aria-labelledby="ai-prompt">
            <div className="flex items-center justify-between gap-3">
              <h2 id="ai-prompt" className="text-sm font-semibold text-ink">Let your AI coding tool install it</h2>
              <CopyButton text={installPrompt(info, selected.name)} label="Copy prompt" />
            </div>
            <p className="text-sm text-ink-secondary">Paste this into Cursor, Claude Code or a similar tool in your website&apos;s project. It has no secret in it.</p>
          </section>

          <section className={`${CARD} space-y-3`} aria-labelledby="widget">
            <h2 id="widget" className="text-sm font-semibold text-ink">1. Widget on your page</h2>
            <CodeBlock title="HTML" code={info.snippets.html} />
          </section>

          <section className={`${CARD} space-y-3`} aria-labelledby="server">
            <h2 id="server" className="text-sm font-semibold text-ink">2. Server code</h2>
            <div role="tablist" aria-label="Server language" className="flex flex-wrap gap-1">
              {SERVER_TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={server === t.id}
                  onClick={() => setServer(t.id)}
                  className={`rounded-lg px-3 py-1 text-xs font-medium ${server === t.id ? "bg-primary/10 text-primary" : "text-ink-secondary hover:bg-surface-mid"}`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <CodeBlock title={server} code={info.snippets[server]} />
          </section>
        </>
      )}
    </div>
  );
}
