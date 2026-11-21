"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { FileText, Film, Image as ImageIcon, Loader2, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { ShopFile, ShopFileKind } from "@/lib/api";
import { cn } from "@/lib/utils";
import { SwitchPill } from "@/components/ui/controls";
import { useShopFiles } from "@/hooks/useApi";

/* Shop files the AI sends in chat (backend services/catalog_files.py): price list PDFs, size charts,
 * shop map photos, short videos. Each has the business's own "send it when" words. */

const KIND_LOOK: Record<ShopFileKind, { label: string; icon: typeof FileText; tint: string }> = {
  document: { label: "PDF", icon: FileText, tint: "bg-amber-50 text-amber-700" },
  image: { label: "Photo", icon: ImageIcon, tint: "bg-sky-50 text-sky-700" },
  video: { label: "Video", icon: Film, tint: "bg-violet-50 text-violet-700" },
};

function sizeText(bytes: number) {
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function ShopFiles({ canManage }: { canManage: boolean }) {
  const { data, error, mutate } = useShopFiles();
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  async function add(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    let added = 0;
    for (const file of Array.from(files)) {
      try {
        await api.catalog.uploadFile(file, {});
        added += 1;
      } catch (err) {
        toast.error(`${file.name}: ${err instanceof Error ? err.message : "couldn't add it"}`);
      }
    }
    setUploading(false);
    if (input.current) input.current.value = "";
    if (added) {
      toast.success(added === 1 ? "Added. Tell Anril when to send it." : `${added} files added. Tell Anril when to send each.`);
      await mutate();
    }
  }

  const aiFiles = (data?.files ?? []).filter((f) => f.ai_enabled && f.send_when);

  return (
    <section aria-labelledby="shop-files" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="shop-files" className="font-display text-lg font-bold text-ink">Files Anril sends in chat</h2>
          <p className="text-sm text-ink-muted">Price lists, size charts, shop map, short videos. Item photos are below.</p>
        </div>
        {canManage && (
          <>
            <input ref={input} type="file" multiple hidden accept="application/pdf,image/jpeg,image/png,video/mp4,video/3gpp"
              onChange={(e) => add(e.target.files)} />
            <button type="button" onClick={() => input.current?.click()} disabled={uploading}
              className="btn-primary inline-flex h-9 items-center gap-1.5 !py-0 disabled:opacity-60">
              {uploading ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />} Add photos or PDF
            </button>
          </>
        )}
      </div>

      {error && (
        <div className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          Couldn&apos;t load the files. <button type="button" onClick={() => mutate()} className="font-semibold underline">Try again</button>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div>
          {!data && !error && (
            <div className="flex items-center gap-2 py-8 text-sm text-ink-muted"><Loader2 size={16} className="animate-spin" /> Loading files…</div>
          )}
          {data && data.files.length === 0 && (
            <div className="rounded-card border border-dashed border-border px-6 py-10 text-center">
              <p className="text-sm font-semibold text-ink">No files yet</p>
              <p className="mx-auto mt-1 max-w-sm text-xs text-ink-muted">
                Add your price list PDF, size chart or a shop video. Anril sends them when a customer asks.
                WhatsApp limits: photo 5 MB, video 16 MB, PDF 50 MB.
              </p>
            </div>
          )}
          {data && data.files.length > 0 && (
            <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {data.files.map((file) => <FileCard key={file.id} file={file} canManage={canManage} onChanged={() => mutate()} />)}
            </ul>
          )}
        </div>

        <aside className="space-y-3">
          <div className="rounded-card border border-border bg-white px-4 py-3 shadow-sm">
            <p className="text-sm font-bold text-ink"><span aria-hidden>🤖</span> When Anril sends them</p>
            {aiFiles.length ? (
              <ul className="mt-2 space-y-1.5 text-sm text-ink">
                {aiFiles.map((f) => (
                  <li key={f.id} className="leading-snug">• &ldquo;{f.send_when}&rdquo; → {f.title}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-xs text-ink-muted">Write &ldquo;Send it when&rdquo; on a file and Anril starts sending it.</p>
            )}
            <p className="mt-2 text-xs text-ink-muted">
              Photos of out-of-stock items are never sent. Anyone with a file&apos;s link can open it, so don&apos;t add private documents.
            </p>
          </div>
          {data && data.no_photo.count > 0 && (
            <div className="rounded-card border border-border bg-white px-4 py-3 shadow-sm">
              <p className="text-sm font-bold text-ink"><span aria-hidden>🏷️</span> Linked to items</p>
              <p className="mt-1 text-sm text-ink-muted">Each item&apos;s photos are below, so price and stock in the reply are always right.</p>
              <p className="mt-2 inline-flex flex-wrap items-center gap-2 text-sm">
                <span className="rounded-full bg-amber-50 px-2 py-0.5 font-semibold text-amber-800">
                  {data.no_photo.count} {data.no_photo.count === 1 ? "item has" : "items have"} no photo
                </span>
                <Link href={`/dashboard/catalog/items/${data.no_photo.items[0]?.id}`} className="font-semibold text-primary hover:underline">Add ›</Link>
              </p>
            </div>
          )}
          {data && data.most_sent.length > 0 && (
            <div className="rounded-card border border-border bg-white px-4 py-3 shadow-sm">
              <p className="text-sm font-bold text-ink"><span aria-hidden>📈</span> Most sent this month</p>
              <p className="mt-1 text-sm text-ink">{data.most_sent.map((f) => `${f.title} ${f.count}×`).join(" · ")}</p>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}

function FileCard({ file, canManage, onChanged }: { file: ShopFile; canManage: boolean; onChanged: () => void }) {
  const look = KIND_LOOK[file.kind];
  const Icon = look.icon;
  const [title, setTitle] = useState(file.title);
  const [when, setWhen] = useState(file.send_when ?? "");
  const [aiOn, setAiOn] = useState(file.ai_enabled);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const dirty = title.trim() !== file.title || when.trim() !== (file.send_when ?? "") || aiOn !== file.ai_enabled;

  async function save(patch: Parameters<typeof api.catalog.updateFile>[1]) {
    setBusy(true);
    try {
      await api.catalog.updateFile(file.id, patch);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api.catalog.deleteFile(file.id);
      toast.success("File removed.");
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't remove it. Try again.");
      setBusy(false);
    }
  }

  const meta = [look.label, file.pages ? `${file.pages} ${file.pages === 1 ? "page" : "pages"}` : null, sizeText(file.size_bytes),
    `sent ${file.sent_count}×`].filter(Boolean).join(" · ");

  return (
    <li className="flex flex-col overflow-hidden rounded-card border border-border bg-white shadow-sm">
      <a href={file.url ?? undefined} target="_blank" rel="noreferrer" className={cn("flex h-24 items-center justify-center", look.tint)}
        aria-label={`Open ${file.title}`}>
        {file.kind === "image" && file.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={file.url} alt="" className="h-full w-full object-cover" />
        ) : (
          <Icon size={30} aria-hidden />
        )}
      </a>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <input value={title} onChange={(e) => setTitle(e.target.value)} disabled={!canManage} maxLength={80} aria-label="File name"
          className="w-full rounded-md border border-transparent bg-transparent px-1 text-sm font-bold text-ink hover:border-border focus:border-primary/40 focus:outline-none" />
        <p className="px-1 text-xs text-ink-muted">{meta}{file.item_name ? ` · ${file.item_name}` : ""}</p>
        <label className="block px-1">
          <span className="text-[11px] font-semibold text-ink-secondary">Send it when the customer…</span>
          <input value={when} onChange={(e) => setWhen(e.target.value)} disabled={!canManage} maxLength={200}
            placeholder="asks for the price list"
            className="mt-0.5 w-full rounded-md border border-border bg-white px-2 py-1 text-xs text-ink focus:border-primary/40 focus:outline-none" />
        </label>
        {canManage && (
          <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle px-1 pt-2">
            <label className="inline-flex items-center gap-2 text-xs font-semibold text-ink-secondary">
              <SwitchPill size="sm" on={aiOn} disabled={busy} onChange={setAiOn}
                aria-label={`Anril may send ${file.title}`} />
              Anril sends it
            </label>
            <div className="flex items-center gap-2">
              {dirty && (
                <button type="button" disabled={busy || !title.trim()} onClick={() => save({ title: title.trim(), send_when: when.trim(), ai_enabled: aiOn })}
                  className="rounded-lg bg-primary px-2.5 py-1 text-xs font-semibold text-white hover:bg-primary-dark disabled:opacity-50">
                  {busy ? <Loader2 size={12} className="animate-spin" /> : "Save"}
                </button>
              )}
              {confirmDelete ? (
                <>
                  <button type="button" onClick={remove} disabled={busy} className="text-xs font-semibold text-red-600">Remove</button>
                  <button type="button" onClick={() => setConfirmDelete(false)} className="text-xs font-semibold text-ink-muted">Keep</button>
                </>
              ) : (
                <button type="button" onClick={() => setConfirmDelete(true)} aria-label={`Remove ${file.title}`}
                  className="rounded-lg p-1 text-ink-muted hover:bg-red-50 hover:text-red-600"><Trash2 size={14} /></button>
              )}
            </div>
          </div>
        )}
      </div>
    </li>
  );
}
