"use client";

import { use, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { ChevronLeft, ExternalLink, FileText, Loader2, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { propertiesApi, type PropertyBody, type SiteVisit } from "@/lib/propertiesApi";
import { useAuthRole } from "../../../contexts/AuthRoleContext";
import { PropertyForm } from "../PropertyForm";

/* One property: its details, photos, brochure (a PDF the AI can send) and upcoming site visits. */

function when(iso: string) {
  return new Date(iso).toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

function VisitRow({ v, action }: { v: SiteVisit; action?: { label: string; run: () => void } }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-white px-3 py-2 text-sm">
      <span className="min-w-0 text-ink">
        <span className="font-semibold">{when(v.start_at)}</span>
        <span className="text-ink-muted"> · {v.customer_name || "Customer"}{v.phone ? ` · ${v.phone}` : ""}</span>
      </span>
      {action && (
        <button type="button" onClick={action.run} className="min-h-9 rounded-lg border border-border px-3 text-xs font-semibold text-ink hover:bg-surface-low">
          {action.label}
        </button>
      )}
    </li>
  );
}

export default function PropertyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { role, permissions, loading } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("catalog.manage");
  const canSeeMoney = role === "owner" || permissions.includes("deals.view") || permissions.includes("deals.manage");
  const photoInput = useRef<HTMLInputElement>(null);
  const brochureInput = useRef<HTMLInputElement>(null);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<"photo" | "brochure" | null>(null);

  const { data: property, error, mutate } = useSWR(["property", id], () => propertiesApi.get(id));
  const { data: visits, mutate: mutateVisits } = useSWR(["property-visits", id], () => propertiesApi.visits(id));

  async function save(body: PropertyBody) {
    setSaving(true);
    try {
      await mutate(await propertiesApi.update(id, body), { revalidate: false });
      toast.success("Saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  async function addPhotos(files: FileList | null) {
    if (!files?.length) return;
    setBusy("photo");
    try {
      for (const file of Array.from(files)) await api.catalog.uploadMedia(id, file);
      await mutate();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not upload the photo");
    } finally {
      setBusy(null);
      if (photoInput.current) photoInput.current.value = "";
    }
  }

  async function addBrochure(file: File | undefined) {
    if (!file) return;
    setBusy("brochure");
    try {
      const old = property?.brochure?.id;
      await api.catalog.uploadFile(file, { title: `${property?.name ?? "Property"} brochure`, send_when: "asks for the brochure or details", catalog_item_id: id });
      if (old) await api.catalog.deleteFile(old).catch(() => undefined);
      await mutate();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not upload the brochure (PDF only)");
    } finally {
      setBusy(null);
      if (brochureInput.current) brochureInput.current.value = "";
    }
  }

  async function run(job: () => Promise<unknown>, failure: string) {
    try {
      await job();
      await Promise.all([mutate(), mutateVisits()]);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : failure);
    }
  }

  async function remove() {
    if (!window.confirm("Delete this property? Its photos and brochure go too. This cannot be undone.")) return;
    try {
      await propertiesApi.remove(id);
      router.push("/dashboard/catalog/properties");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not delete");
    }
  }

  if (loading || (!property && !error)) return <div className="min-h-[240px] animate-pulse rounded-card bg-surface-low" />;
  if (error || !property) return <p className="py-16 text-center text-sm text-ink-muted">This property was not found.</p>;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Link href="/dashboard/catalog/properties" className="inline-flex items-center gap-1 text-sm font-semibold text-primary">
        <ChevronLeft className="h-4 w-4" aria-hidden /> Properties
      </Link>
      <h1 className="text-lg font-bold text-ink">{property.name}</h1>

      {canManage ? (
        <PropertyForm key={property.id + String(property.units_left)} initial={property} canSeeMoney={canSeeMoney} saving={saving} submitLabel="Save changes" onSubmit={save} />
      ) : (
        <p className="rounded-card border border-border bg-white p-4 text-sm text-ink-muted">You can look at this property but not change it.</p>
      )}

      <section className="space-y-2 rounded-card border border-border bg-white p-4 shadow-sm">
        <h2 className="text-sm font-bold text-ink">Photos</h2>
        <div className="flex flex-wrap gap-2">
          {(property.photos ?? []).map((ph) => (
            <div key={ph.id} className="relative h-24 w-24 overflow-hidden rounded-lg border border-border">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={ph.url} alt={ph.label || property.name} className="h-full w-full object-cover" />
              {canManage && (
                <button
                  type="button"
                  aria-label="Remove this photo"
                  onClick={() => run(() => api.catalog.deleteMedia(ph.id), "Could not remove the photo")}
                  className="absolute right-1 top-1 rounded-full bg-white/90 p-1 text-red-700"
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                </button>
              )}
            </div>
          ))}
          {canManage && (
            <button
              type="button"
              disabled={busy === "photo"}
              onClick={() => photoInput.current?.click()}
              className="flex h-24 w-24 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border text-xs font-semibold text-ink-muted hover:bg-surface-low"
            >
              {busy === "photo" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Upload className="h-4 w-4" aria-hidden />}
              Add photos
            </button>
          )}
        </div>
        <input ref={photoInput} type="file" accept="image/jpeg,image/png" multiple hidden onChange={(e) => addPhotos(e.target.files)} />
        <p className="text-xs text-ink-muted">The AI agent sends these when a customer asks to see the property.</p>
      </section>

      <section className="space-y-2 rounded-card border border-border bg-white p-4 shadow-sm">
        <h2 className="text-sm font-bold text-ink">Brochure</h2>
        {property.brochure ? (
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <a href={property.brochure.url ?? "#"} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 font-semibold text-primary">
              <FileText className="h-4 w-4" aria-hidden /> {property.brochure.title || "Brochure"}
              {property.brochure.pages ? <span className="font-normal text-ink-muted">· {property.brochure.pages} pages</span> : null}
            </a>
            {canManage && (
              <button
                type="button"
                onClick={() => run(() => api.catalog.deleteFile(property.brochure!.id), "Could not remove the brochure")}
                className="min-h-9 rounded-lg border border-border px-3 text-xs font-semibold text-red-700"
              >
                Remove
              </button>
            )}
          </div>
        ) : (
          <p className="text-sm text-ink-muted">No brochure yet.</p>
        )}
        {canManage && (
          <button
            type="button"
            disabled={busy === "brochure"}
            onClick={() => brochureInput.current?.click()}
            className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-border px-3 text-xs font-semibold text-ink hover:bg-surface-low"
          >
            {busy === "brochure" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Upload className="h-4 w-4" aria-hidden />}
            {property.brochure ? "Replace brochure (PDF)" : "Add brochure (PDF)"}
          </button>
        )}
        <input ref={brochureInput} type="file" accept="application/pdf" hidden onChange={(e) => addBrochure(e.target.files?.[0])} />
      </section>

      <section className="space-y-2 rounded-card border border-border bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-bold text-ink">Site visits</h2>
          <Link href="/dashboard/bookings" className="inline-flex items-center gap-1 text-xs font-semibold text-primary">
            Open Bookings <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </Link>
        </div>
        {visits && !visits.allowed && <p className="text-sm text-ink-muted">You need Bookings access to see visits.</p>}
        {visits?.allowed && (
          <>
            {!visits.service_ready && <p className="text-sm text-ink-muted">The &quot;Site visit&quot; booking is made the first time you save a property.</p>}
            {visits.service_ready && visits.mine.length === 0 && <p className="text-sm text-ink-muted">No upcoming visits for this property.</p>}
            <ul className="space-y-2">
              {visits.mine.map((v) => (
                <VisitRow key={v.id} v={v} action={canManage ? { label: "Not this property", run: () => run(() => propertiesApi.detachVisit(id, v.id), "Could not update") } : undefined} />
              ))}
            </ul>
            {visits.others.length > 0 && (
              <>
                <p className="pt-2 text-xs font-semibold text-ink-muted">Other upcoming site visits (not tied to a property yet)</p>
                <ul className="space-y-2">
                  {visits.others.map((v) => (
                    <VisitRow key={v.id} v={v} action={canManage ? { label: "This property", run: () => run(() => propertiesApi.attachVisit(id, v.id), "Could not update") } : undefined} />
                  ))}
                </ul>
              </>
            )}
            <p className="text-xs text-ink-muted">
              Customers book a visit with the booking link. In Bookings, add who shows the property (staff or a column) and their hours.
              The reminder before the visit is the one Bookings already sends.
            </p>
          </>
        )}
      </section>

      {canManage && (
        <button type="button" onClick={remove} className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-red-200 px-4 text-sm font-semibold text-red-700">
          <Trash2 className="h-4 w-4" aria-hidden /> Delete property
        </button>
      )}
    </div>
  );
}
