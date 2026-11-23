"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { companionsApi, type CompanionInstall } from "@/lib/api";
import { CharacterSelect, useCharacters } from "@/components/agents/CharacterSelect";
import { CodeBlock, CopyButton } from "@/components/agents/CodeBlock";
import { OPENAPI_PATH, appPrompt, installPrompt } from "@/components/agents/installPrompt";
import { CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";

const SERVER_TABS = [
  { id: "python", label: "Python" },
  { id: "node", label: "Node" },
] as const;

const CHAT_TABS = [
  { id: "chat_python", label: "Python" },
  { id: "chat_node", label: "Node" },
  { id: "chat_php", label: "PHP" },
  { id: "curl", label: "curl" },
] as const;

const PATHS = [
  { id: "app", label: "In your own app", hint: "Your chat screen, your design. Your server calls Anril." },
  { id: "web", label: "Chat bubble on your website", hint: "Two script tags. Anril draws the chat." },
] as const;

function Tabs<T extends string>({ label, tabs, value, onChange }: {
  label: string; tabs: readonly { id: T; label: string }[]; value: T; onChange: (id: T) => void;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`rounded-lg px-3 py-1 text-xs font-medium ${value === t.id ? "bg-primary/10 text-primary" : "text-ink-secondary hover:bg-surface-mid"}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** Copy-paste install for one character. Own app first (server calls /chat), website widget second. */
export default function InstallPage() {
  const { characters, selected, select, error: listError } = useCharacters();
  const [info, setInfo] = useState<CompanionInstall | null>(null);
  const [error, setError] = useState("");
  const [server, setServer] = useState<(typeof SERVER_TABS)[number]["id"]>("python");
  const [chatLang, setChatLang] = useState<(typeof CHAT_TABS)[number]["id"]>("chat_python");
  const [path, setPath] = useState<(typeof PATHS)[number]["id"]>("app");

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

          <fieldset className="space-y-2">
            <legend className="text-sm text-ink-secondary">Where will your customers chat?</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {PATHS.map((p) => (
                <label
                  key={p.id}
                  className={`cursor-pointer rounded-xl border p-3 focus-within:ring-2 focus-within:ring-primary/40 ${path === p.id ? "border-primary ring-1 ring-primary" : "border-border-subtle hover:bg-surface-mid"}`}
                >
                  <input type="radio" name="install-path" value={p.id} checked={path === p.id} onChange={() => setPath(p.id)} className="sr-only" />
                  <span className="block text-sm font-semibold text-ink">{p.label}</span>
                  <span className="block text-sm text-ink-secondary">{p.hint}</span>
                </label>
              ))}
            </div>
          </fieldset>

          {path === "app" ? (
            <>
              <section className={`${CARD} space-y-2`} aria-labelledby="app-prompt">
                <div className="flex items-center justify-between gap-3">
                  <h2 id="app-prompt" className="text-sm font-semibold text-ink">Let your AI coding tool connect it</h2>
                  <CopyButton text={appPrompt(info, selected.name)} label="Copy setup prompt" />
                </div>
                <p className="text-sm text-ink-secondary">
                  Paste this into Claude Code, Cursor or a similar tool, opened in your backend project (any language). It covers
                  profiles, your data, the reply, errors and deletes. It has no secret in it.
                </p>
              </section>

              <section className={`${CARD} space-y-3`} aria-labelledby="chat-call">
                <h2 id="chat-call" className="text-sm font-semibold text-ink">Or write it yourself: one call per message</h2>
                <p className="text-sm text-ink-secondary">
                  Your server sends the user&apos;s message, their user id, the selected profile id and what you know about
                  that profile. Anril keeps a separate memory for each user and profile. Keep the key in ANRIL_COMPANION_KEY on
                  your server, never in the app.
                </p>
                <Tabs label="Language" tabs={CHAT_TABS} value={chatLang} onChange={setChatLang} />
                <CodeBlock title={chatLang === "curl" ? "curl" : chatLang.replace("chat_", "")} code={info.snippets[chatLang]} />
                <p className="text-sm text-ink-secondary">
                  Deleted a profile or an account? POST {info.api_base}/api/v1/companion/forget with its user_id and profile_id.{" "}
                  <a href={OPENAPI_PATH} download className="font-medium text-primary underline">Download the API description (OpenAPI)</a>
                </p>
              </section>
            </>
          ) : (
            <>
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
                <h2 id="server" className="text-sm font-semibold text-ink">2. Server code (signs the user)</h2>
                <Tabs label="Server language" tabs={SERVER_TABS} value={server} onChange={setServer} />
                <CodeBlock title={server} code={info.snippets[server]} />
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}
