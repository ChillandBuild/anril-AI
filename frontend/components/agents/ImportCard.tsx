"use client";
import { useRef, useState } from "react";
import { FileText, UploadCloud, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { ACCEPT, type KnowledgeTag } from "@/components/agents/knowledgeRows";
import { BTN_PRIMARY, CARD, INPUT } from "@/components/agents/ui";

/**
 * Drop files, pick a tag, Import. Example: "Porutham guide.pdf" under
 * "astrology books" → uploaded through the existing knowledge upload with
 * that tag, so only characters reading that tag see it.
 */
export function ImportCard({
  tags,
  defaultTagId,
  onUploaded,
}: {
  tags: KnowledgeTag[];
  defaultTagId: string | null;
  onUploaded: (docIds: string[]) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [tagId, setTagId] = useState<string>(defaultTagId ?? "");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const effectiveTag = tagId || defaultTagId || "";

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    setError("");
    setFiles((prev) => [...prev, ...Array.from(list).filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size))]);
  };

  const importAll = async () => {
    if (!effectiveTag) return setError("Pick a tag first. Characters read only the tag they are set to.");
    setBusy(true);
    setError("");
    const ids: string[] = [];
    const failed: string[] = [];
    for (const file of files) {
      try {
        const row = (await api.knowledge.uploadDocument(file, effectiveTag)) as { id?: string };
        if (row?.id) ids.push(row.id);
      } catch (e) {
        failed.push(`${file.name}: ${(e as Error).message || "upload failed"}`);
      }
    }
    setBusy(false);
    setFiles((prev) => prev.filter((f) => failed.some((line) => line.startsWith(`${f.name}:`))));
    if (failed.length) setError(failed.join(" · "));
    if (ids.length) onUploaded(ids);
  };

  return (
    <section className={cn(CARD, "space-y-4")} aria-labelledby="import-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="import-title" className="text-sm font-semibold text-ink">Import documents</h2>
        <label className="flex items-center gap-2 text-sm text-ink-secondary">
          Tag
          <select value={effectiveTag} onChange={(e) => setTagId(e.target.value)} className={cn(INPUT, "w-auto min-w-[180px] py-1.5")}>
            <option value="">Pick a tag</option>
            {tags.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </label>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          addFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors",
          dragging ? "border-primary bg-primary/5" : "border-border",
        )}
      >
        <UploadCloud size={24} className="text-ink-muted" aria-hidden="true" />
        <p className="text-sm text-ink-secondary">
          Drop files here or{" "}
          <button type="button" onClick={() => inputRef.current?.click()} className="font-medium text-primary underline underline-offset-2">
            browse
          </button>
        </p>
        <p className="text-xs text-ink-muted">PDF, Word, PowerPoint, Excel, CSV or text.</p>
        <input ref={inputRef} type="file" multiple accept={ACCEPT} className="sr-only" aria-label="Choose files" onChange={(e) => {
          addFiles(e.target.files);
          e.target.value = "";
        }} />
      </div>

      {files.length > 0 && (
        <ul className="space-y-1">
          {files.map((f) => (
            <li key={`${f.name}-${f.size}`} className="flex items-center gap-2 rounded-lg bg-surface-mid px-3 py-1.5 text-sm">
              <FileText size={14} className="text-ink-muted" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">{f.name}</span>
              <button type="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles((p) => p.filter((x) => x !== f))} className="text-ink-muted hover:text-danger">
                <X size={14} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="rounded-xl border border-border-subtle bg-surface-mid/50 px-3 py-2 text-xs text-ink-secondary">
        <span className="font-medium text-ink">Facts only.</span> Tagged files give your characters facts to read. They won&apos;t change Anril&apos;s Business Description.
      </div>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      <div className="flex justify-end">
        <button type="button" onClick={importAll} disabled={busy || files.length === 0} className={BTN_PRIMARY}>
          {busy ? "Importing…" : files.length > 1 ? `Import ${files.length} files` : "Import"}
        </button>
      </div>
    </section>
  );
}
