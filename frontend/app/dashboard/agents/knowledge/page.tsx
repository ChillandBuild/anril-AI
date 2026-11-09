"use client";
import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { api, companionsApi, type ApiError, type Companion } from "@/lib/api";
import { ImportCard } from "@/components/agents/ImportCard";
import { docState, tagRows, type KnowledgeDocLite, type KnowledgeTag } from "@/components/agents/knowledgeRows";
import { CARD, ErrorNote, LoadingRows, formatDate } from "@/components/agents/ui";

const POLL_MS = 3000;

export default function AgentsKnowledgePage() {
  const [tags, setTags] = useState<KnowledgeTag[] | null>(null);
  const [docs, setDocs] = useState<KnowledgeDocLite[]>([]);
  const [characters, setCharacters] = useState<Companion[]>([]);
  const [error, setError] = useState("");
  const [watching, setWatching] = useState<string[]>([]);

  const load = useCallback(() => {
    setError("");
    Promise.all([api.knowledge.listCampaignTags(), api.knowledge.listDocuments(), companionsApi.list()])
      .then(([t, d, c]) => {
        setTags(t);
        setDocs(d);
        setCharacters(c);
      })
      .catch((e: ApiError) =>
        setError(
          e.status === 403
            ? "Your role can't open documents. Ask the owner to give it Knowledge access too."
            : e.message || "Could not load your documents.",
        ),
      );
  }, []);
  useEffect(load, [load]);

  // Poll only while a file we just imported is still being read.
  const processing = watching.filter((id) => {
    const doc = docs.find((d) => d.id === id);
    return !doc || docState(doc) === "processing";
  });
  useEffect(() => {
    if (processing.length === 0) return;
    const timer = setInterval(() => {
      api.knowledge.listDocuments().then(setDocs).catch(() => undefined);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [processing.length]);

  if (error) return <div className="mx-auto max-w-5xl p-4 sm:p-6"><ErrorNote message={error} onRetry={load} /></div>;
  if (tags === null) return <div className="mx-auto max-w-5xl p-4 sm:p-6"><LoadingRows rows={4} /></div>;

  const defaultTag = characters.find((c) => c.status === "live" && c.knowledge_tag_id)?.knowledge_tag_id ?? characters.find((c) => c.knowledge_tag_id)?.knowledge_tag_id ?? null;
  const rows = tagRows(tags, docs, characters);
  const watched = watching.map((id) => docs.find((d) => d.id === id)).filter(Boolean) as KnowledgeDocLite[];

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <ImportCard
        tags={tags}
        defaultTagId={defaultTag}
        onUploaded={(ids) => {
          setWatching((w) => [...ids, ...w]);
          api.knowledge.listDocuments().then(setDocs).catch(() => undefined);
        }}
      />

      {watching.length > 0 && (
        <section className={CARD} aria-labelledby="processing-title" aria-live="polite">
          <h2 id="processing-title" className="mb-2 text-sm font-semibold text-ink">
            {processing.length > 0 ? `Processing ${processing.length} file${processing.length > 1 ? "s" : ""}` : "Imported"}
          </h2>
          <ul className="space-y-1.5 text-sm">
            {watched.map((d) => {
              const state = docState(d);
              return (
                <li key={d.id} className="flex items-center gap-2">
                  {state === "processing" ? (
                    <Loader2 size={14} className="animate-spin text-ink-muted" aria-hidden="true" />
                  ) : state === "failed" ? (
                    <XCircle size={14} className="text-danger" aria-hidden="true" />
                  ) : (
                    <CheckCircle2 size={14} className="text-success" aria-hidden="true" />
                  )}
                  <span className="min-w-0 flex-1 truncate">{d.name}</span>
                  <span className={state === "failed" ? "text-danger" : "text-ink-muted"}>
                    {state === "processing" ? "Reading…" : state === "failed" ? d.error_message || "Failed" : "Ready"}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section className={`${CARD} overflow-x-auto p-0`} aria-labelledby="tags-title">
        <h2 id="tags-title" className="px-5 pt-4 text-sm font-semibold text-ink">Tags your characters read</h2>
        {rows.length === 0 ? (
          <p className="px-5 pb-5 pt-2 text-sm text-ink-secondary">No tagged documents yet. Import one above, then pick its tag on a character&apos;s Knowledge tab.</p>
        ) : (
          <table className="mt-2 w-full min-w-[520px] text-left text-sm">
            <thead className="border-y border-border-subtle text-xs uppercase tracking-wide text-ink-muted">
              <tr>
                <th scope="col" className="px-5 py-2.5 font-medium">Tag</th>
                <th scope="col" className="px-5 py-2.5 font-medium">Files</th>
                <th scope="col" className="px-5 py-2.5 font-medium">Read by</th>
                <th scope="col" className="px-5 py-2.5 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-border-subtle last:border-0">
                  <td className="px-5 py-3 font-medium text-ink">{r.name}</td>
                  <td className="px-5 py-3 text-ink-secondary">{r.files}</td>
                  <td className="px-5 py-3 text-ink-secondary">{r.readBy.length ? r.readBy.join(", ") : "No character yet"}</td>
                  <td className="px-5 py-3 text-ink-secondary">{formatDate(r.updated)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
