"use client";

import { useEffect, useState } from "react";
import { Undo2 } from "lucide-react";
import { toast } from "sonner";
import {
  fetchBusinessDetails,
  imageProblem,
  removeBrandImage,
  saveBusinessDetails,
  uploadBrandImage,
  withDefaults,
  EMPTY_BUSINESS_DETAILS,
  type BrandImageKind,
  type BusinessDetails,
} from "@/lib/businessDetailsApi";
import { BUSINESS_DETAILS_GROUPS, BusinessDetailsFields } from "@/components/business-details/BusinessDetailsFields";
import { InvoicePreview } from "@/components/business-details/InvoicePreview";
import { businessDetailErrors } from "@/components/business-details/validate";
import { SaveButton, SaveStatus } from "../SettingsSection";
import { useSettingsForm } from "../SettingsFormContext";
import { AiraLoader } from "@/components/AiraLoader";

/** The part of the details the form edits: pictures and their links are handled on their own. */
function typedFields(d: BusinessDetails) {
  const { has_logo, has_signature, logo_url, signature_url, ...rest } = d;
  void has_logo; void has_signature; void logo_url; void signature_url;
  return rest;
}

export default function AccountSettingsPage() {
  const { canManageSettings } = useSettingsForm();

  const [profile, setProfile] = useState<BusinessDetails>(EMPTY_BUSINESS_DETAILS);
  const [draft, setDraft] = useState<BusinessDetails>(EMPTY_BUSINESS_DETAILS);
  const [pictures, setPictures] = useState<{ logo: string | null; signature: string | null }>({ logo: null, signature: null });
  const [busyImage, setBusyImage] = useState<BrandImageKind | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [showErrors, setShowErrors] = useState(false);

  function adopt(data: BusinessDetails, keepDraft = false) {
    setProfile(data);
    if (!keepDraft) setDraft(data);
    setPictures({ logo: data.logo_url ?? null, signature: data.signature_url ?? null });
  }

  useEffect(() => {
    fetchBusinessDetails()
      .then((data) => adopt(data))
      .catch((err) => {
        toast.error(err instanceof Error ? err.message : "Failed to load business details");
      })
      .finally(() => setIsLoading(false));
  }, []);

  const isDirty = JSON.stringify(typedFields(draft)) !== JSON.stringify(typedFields(profile));
  const errors = businessDetailErrors(draft);
  const hasErrors = Object.keys(errors).length > 0;

  async function handleSave() {
    if (!canManageSettings) return;
    if (hasErrors) {
      setShowErrors(true);
      const n = Object.keys(errors).length;
      toast.error(`${n} field${n === 1 ? " needs" : "s need"} fixing before you can save`);
      requestAnimationFrame(() => document.querySelector("[data-field-error]")?.scrollIntoView({ behavior: "smooth", block: "center" }));
      return;
    }
    setSaveState("saving");
    try {
      const saved = await saveBusinessDetails(typedFields(draft));
      adopt(saved);
      setSaveState("saved");
      toast.success("Business details saved");
      setTimeout(() => setSaveState("idle"), 2000);
    } catch (err) {
      setSaveState("idle");
      toast.error(err instanceof Error ? err.message : "Failed to save business details");
    }
  }

  async function handlePickImage(kind: BrandImageKind, file: File) {
    const problem = imageProblem(file);
    if (problem) {
      toast.error(problem);
      return;
    }
    setBusyImage(kind);
    try {
      // The picture saves on its own; whatever is typed but not saved yet stays as it is.
      adopt(withDefaults(await uploadBrandImage(kind, file)), true);
      toast.success(kind === "logo" ? "Logo saved" : "Signature saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save the picture");
    } finally {
      setBusyImage(null);
    }
  }

  async function handleRemoveImage(kind: BrandImageKind) {
    setBusyImage(kind);
    try {
      adopt(await removeBrandImage(kind), true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't remove the picture");
    } finally {
      setBusyImage(null);
    }
  }

  return (
    <div className="flex flex-wrap items-start gap-4">
      <div className="flex min-w-0 flex-[3_1_560px] flex-col gap-3.5">
        {isLoading ? (
          <div className="rounded-2xl border border-border/70 bg-white p-5">
            <AiraLoader inline className="min-h-[120px]" />
          </div>
        ) : (
          BUSINESS_DETAILS_GROUPS.map((g) => (
            <section key={g.id} className="rounded-2xl border border-border/70 bg-white p-5 shadow-[0_1px_2px_rgba(28,25,23,0.03)]">
              <div className="mb-4">
                <h2 className="font-display text-base font-bold text-ink">{g.title}</h2>
                <p className="font-body text-xs text-ink-secondary">{g.hint}</p>
              </div>
              <BusinessDetailsFields
                group={g.id}
                draft={draft}
                onChange={(patch) => setDraft((prev) => ({ ...prev, ...patch }))}
                errors={showErrors ? errors : {}}
                canManage={canManageSettings}
                logoUrl={pictures.logo}
                signatureUrl={pictures.signature}
                busyImage={busyImage}
                onPickImage={handlePickImage}
                onRemoveImage={handleRemoveImage}
              />
            </section>
          ))
        )}

        <div className="sticky bottom-[calc(var(--mobile-nav-h)+env(safe-area-inset-bottom,0px)+0.5rem)] lg:bottom-3 z-10 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border/70 bg-white px-4 py-3 shadow-[0_8px_24px_rgba(10,21,40,0.10)]">
          <div className="flex min-h-[20px] items-center">
            <SaveStatus state={saveState} dirty={isDirty} />
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setDraft(profile);
                setShowErrors(false);
              }}
              disabled={!isDirty || saveState === "saving" || isLoading}
              className="inline-flex items-center gap-1.5 rounded-xl border border-border px-4 py-2 font-label text-sm font-semibold text-ink transition hover:bg-surface-low disabled:cursor-default disabled:opacity-50"
            >
              <Undo2 size={14} aria-hidden /> Undo
            </button>
            <SaveButton state={saveState} dirty={isDirty} disabled={!canManageSettings || isLoading} onClick={handleSave} />
          </div>
        </div>
      </div>

      <aside className="flex min-w-0 flex-[2_1_380px] flex-col gap-2.5 lg:sticky lg:top-3">
        <div className="flex items-center justify-between">
          <span className="font-label text-xs font-bold uppercase tracking-wider text-ink-secondary">Bill preview</span>
          <span className="font-body text-xs text-ink-secondary">Updates as you type</span>
        </div>
        <InvoicePreview details={draft} logoUrl={pictures.logo} signatureUrl={pictures.signature} />
      </aside>
    </div>
  );
}
