"use client";

import { useEffect, useState } from "react";
import { Building2, Crown, Eye, Lock, MapPin, Receipt, UserCircle } from "lucide-react";
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
import { BusinessDetailsFields } from "@/components/business-details/BusinessDetailsFields";
import { InvoicePreview } from "@/components/business-details/InvoicePreview";
import { businessDetailErrors } from "@/components/business-details/validate";
import { PasskeySettings } from "@/app/dashboard/profile/PasskeySettings";
import { useAuthRole } from "../../contexts/AuthRoleContext";
import {
  Fact,
  Facts,
  SaveButton,
  SaveStatus,
  SectionFooter,
  SettingsAccordion,
  SettingsSection,
  SummaryHint,
} from "../SettingsSection";
import { useSettingsForm } from "../SettingsFormContext";
import ChangePasswordCard from "../ChangePasswordCard";
import { AiraLoader } from "@/components/AiraLoader";

/** The part of the details the form edits: pictures and their links are handled on their own. */
function typedFields(d: BusinessDetails) {
  const { has_logo, has_signature, logo_url, signature_url, ...rest } = d;
  void has_logo; void has_signature; void logo_url; void signature_url;
  return rest;
}

export default function AccountSettingsPage() {
  const { fullName, initials, email, memberSince, canManageSettings } = useSettingsForm();
  const { tenantName } = useAuthRole();

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
    <SettingsAccordion defaultOpenId="profile">
      {/* Your profile always opens first here: an exception to the
          "two or more sections start closed" rule. */}

      <SettingsSection
        id="profile"
        icon={UserCircle}
        accent="violet"
        title="Your profile"
        description="Who's signed in, and since when."
        summary={
          <Facts>
            <Fact icon={UserCircle}>{fullName}</Fact>
            {email && <Fact>{email}</Fact>}
            {tenantName && <Fact icon={Building2}>{tenantName}</Fact>}
          </Facts>
        }
      >
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[var(--primary-950)] to-primary text-sm font-bold text-white shadow-md shadow-primary/20">
            {initials}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-display text-sm font-bold text-ink">{fullName}</span>
              <span className="badge-violet inline-flex items-center gap-1 px-2 py-0.5 font-label text-[10px] font-bold uppercase tracking-wider">
                <Crown size={11} />
                Admin
              </span>
            </div>
            {email && <p className="break-all font-body text-xs text-ink-muted">{email}</p>}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3 sm:gap-4">
          {tenantName && (
            <span className="font-label text-xs text-ink-muted">Workspace: {tenantName}</span>
          )}
          {memberSince && (
            <span className="font-label text-xs text-ink-muted">Member since {memberSince}</span>
          )}
          <span className="flex items-center gap-1.5 font-label text-xs text-emerald-600">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            All systems online
          </span>
        </div>
      </SettingsSection>

      <SettingsSection
        id="security"
        icon={Lock}
        accent="sky"
        title="Sign-in & security"
        description="Your password and the passkeys you can sign in with instead."
      >
        <div className="space-y-5">
          <ChangePasswordCard />
          <PasskeySettings />
        </div>
      </SettingsSection>

      {/* Anchor for /dashboard/settings/business, which redirects to #business */}
      <div id="business">
        <SettingsSection
          id="business-details"
          icon={Building2}
          accent="violet"
          title="Business details"
          description="What your bills say: name, address, GST, UPI and bank, terms, logo and signature. Also used on the monthly export for your auditor."
          dirty={isDirty}
          summary={
            isLoading ? undefined : profile.legal_name.trim() ? (
              <Facts>
                <Fact icon={Building2}>{profile.legal_name}</Fact>
                {profile.city.trim() && <Fact icon={MapPin}>{profile.city}</Fact>}
                <Fact icon={Receipt} mono={profile.gst_type === "regular" && !!profile.gstin}>
                  {profile.gst_type === "composition"
                    ? "Composition (bill of supply)"
                    : profile.gst_type === "none"
                      ? "Not GST registered"
                      : profile.gstin
                        ? `GSTIN ${profile.gstin}`
                        : "No GSTIN"}
                </Fact>
                {profile.bill_prefix && <Fact mono>Bills {profile.bill_prefix}/…</Fact>}
                <Fact>{profile.prices_include_gst ? "Prices include GST" : "GST added at checkout"}</Fact>
              </Facts>
            ) : (
              <SummaryHint>Not filled in yet. Your auditor&apos;s monthly export uses these details.</SummaryHint>
            )
          }
        >
          {isLoading ? (
            <AiraLoader inline className="min-h-[120px]" />
          ) : (
            <div className="space-y-7">
              <BusinessDetailsFields
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
              <section>
                <h3 className="mb-3 inline-flex items-center gap-1.5 font-display text-sm font-bold text-ink">
                  <Eye size={15} aria-hidden /> Bill preview
                </h3>
                <InvoicePreview details={draft} logoUrl={pictures.logo} signatureUrl={pictures.signature} />
              </section>
            </div>
          )}

          <SectionFooter status={<SaveStatus state={saveState} dirty={isDirty} />}>
            <SaveButton state={saveState} dirty={isDirty} disabled={!canManageSettings || isLoading} onClick={handleSave} />
          </SectionFooter>
        </SettingsSection>
      </div>
    </SettingsAccordion>
  );
}
