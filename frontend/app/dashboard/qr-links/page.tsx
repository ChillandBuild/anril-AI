"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Download, Loader2, Plus } from "lucide-react";
import { uniqueNames, zipStore } from "@/lib/zipStore";
import { ConfirmModal } from "@/components/ConfirmModal";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { createQrLink, listQrLinks, updateQrLink, type QrLink, type QrList } from "@/lib/qrLinksApi";
import { QrCard } from "./QrCard";
import { QrForm, type QrFormResult } from "./QrForm";
import { PrintDialog } from "./PrintDialog";

const businessNameFor = (name: string | null) => (name ?? "").trim();

export default function QrLinksPage() {
  const { role, permissions, tenantName, loading: roleLoading } = useAuthRole();
  const canView = role === "owner" || permissions.includes("numbers.view") || permissions.includes("numbers.manage");
  const canManage = role === "owner" || permissions.includes("numbers.manage");

  const [data, setData] = useState<QrList | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<QrLink | null>(null);
  const [printing, setPrinting] = useState<QrLink | null>(null);
  const [archiving, setArchiving] = useState<QrLink | null>(null);
  const [archiveBusy, setArchiveBusy] = useState(false);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setData(await listQrLinks());
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Couldn't load your QR codes.");
    }
  }, []);

  useEffect(() => {
    if (canView) void load();
  }, [canView, load]);

  async function save(values: QrFormResult) {
    if (editing) {
      await updateQrLink(editing.id, values);
      toast.success("Saved");
    } else {
      await createQrLink(values);
      toast.success("QR made");
    }
    setEditing(null);
    setCreating(false);
    await load();
  }

  async function setArchived(link: QrLink, archived: boolean) {
    try {
      await updateQrLink(link.id, { archived });
      toast.success(archived ? "Archived" : "Back in use");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't change that. Try again.");
    }
  }

  // Download all: every QR in use (not archived), each as its own PNG, in one .zip.
  async function downloadAll() {
    const canvases = Array.from(document.querySelectorAll<HTMLCanvasElement>("canvas[data-qr-file]"));
    if (!canvases.length) return;
    const blobs = await Promise.all(canvases.map((c) => new Promise<Blob | null>((ok) => c.toBlob(ok, "image/png"))));
    const names = uniqueNames(canvases.map((c) => c.dataset.qrFile || "qr.png"));
    const files = await Promise.all(blobs.map(async (b, i) => ({ name: names[i], data: new Uint8Array(await (b as Blob).arrayBuffer()) })));
    const url = URL.createObjectURL(zipStore(files.filter((f) => f.data.length)));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(businessNameFor(tenantName) || "qr-codes").replace(/[^\w-]+/g, "-")}-qr-codes.zip`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast.success(`${files.length} QR ${files.length === 1 ? "code" : "codes"} downloaded`);
  }

  if (roleLoading) return <div className="flex items-center justify-center gap-2 py-20 text-sm text-ink-muted"><Loader2 size={16} className="animate-spin" /> Loading…</div>;
  if (!canView) return <p className="py-20 text-center text-sm text-ink-muted">You don&apos;t have access to QR &amp; links.</p>;

  const items = data?.items ?? [];
  const businessName = (tenantName ?? "").trim();

  return (
    <div className="w-full space-y-4 px-4 py-4 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="max-w-prose text-sm text-ink-muted">Print a QR for each place. When a customer scans it, WhatsApp opens with your first message, and you see which QR brought them.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {items.some((l) => !l.archived) && (
            <button type="button" onClick={() => void downloadAll()} className="inline-flex h-9 items-center gap-2 rounded-xl border border-border bg-white px-4 text-sm font-semibold text-ink hover:bg-surface-low">
              <Download size={16} /> Download all
            </button>
          )}
          {canManage && !creating && !editing && (
            <button type="button" onClick={() => setCreating(true)} className="inline-flex h-11 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white hover:bg-primary-dark">
              <Plus size={16} /> New QR
            </button>
          )}
        </div>
      </div>

      {(creating || editing) && canManage && (
        <QrForm key={editing?.id ?? "new"} link={editing ?? undefined} places={data?.places ?? []} onSave={save}
          onCancel={() => { setCreating(false); setEditing(null); }} />
      )}

      {data === null && !loadError && (
        <div className="flex items-center justify-center gap-2 rounded-card border border-border bg-white py-16 text-sm text-ink-muted"><Loader2 size={16} className="animate-spin" /> Loading…</div>
      )}
      {loadError && (
        <div role="alert" className="rounded-card border border-danger/30 bg-white px-4 py-6 text-center text-sm text-ink">
          <p>{loadError}</p>
          <button type="button" onClick={load} className="mt-3 inline-flex h-11 items-center rounded-xl border border-border px-4 font-semibold hover:bg-surface-low">Try again</button>
        </div>
      )}
      {data && items.length === 0 && (
        <div className="rounded-card border border-dashed border-border bg-white px-4 py-12 text-center text-sm text-ink-muted">
          No QR codes yet.{canManage ? " Press New QR to make your first one." : ""}
        </div>
      )}

      {items.length > 0 && (
        <ul className="space-y-3">
          {items.map((link) => (
            <QrCard key={link.id} link={link} canManage={canManage}
              onEdit={() => { setCreating(false); setEditing(link); }}
              onPrint={() => setPrinting(link)}
              onToggleArchive={() => (link.archived ? setArchived(link, false) : setArchiving(link))} />
          ))}
        </ul>
      )}

      {printing && <PrintDialog link={printing} businessName={businessName} onClose={() => setPrinting(null)} />}

      <ConfirmModal
        open={!!archiving}
        onClose={() => setArchiving(null)}
        title="Archive this QR?"
        description={archiving ? `Anyone who scans "${archiving.name}" will see "This QR is no longer in use". You can bring it back later. Your numbers stay.` : ""}
        tone="warning"
        confirmLabel="Archive"
        loading={archiveBusy}
        onConfirm={async () => {
          if (!archiving) return;
          setArchiveBusy(true);
          await setArchived(archiving, true);
          setArchiveBusy(false);
          setArchiving(null);
        }}
      />
    </div>
  );
}
