"use client";

import { useEffect, useState } from "react";
import { Building2, Crown, Lock, UserCircle } from "lucide-react";
import { toast } from "sonner";
import { api, BusinessProfile } from "@/lib/api";
import { PasskeySettings } from "@/app/dashboard/profile/PasskeySettings";
import { useAuthRole } from "../../contexts/AuthRoleContext";
import { SaveButton, SaveStatus, SectionFooter, SettingsAccordion, SettingsSection, SwitchPill } from "../SettingsSection";
import { useSettingsForm } from "../SettingsFormContext";
import ChangePasswordCard from "../ChangePasswordCard";
import { AiraLoader } from "@/components/AiraLoader";

const EMPTY: BusinessProfile = {
  legal_name: "",
  address: "",
  city: "",
  state: "",
  pincode: "",
  gstin: "",
  email: "",
  phone: "",
  prices_include_gst: true,
};

const GSTIN_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

type FieldKey = "legal_name" | "address" | "city" | "state" | "pincode" | "email" | "phone";

const TEXT_FIELDS: { key: FieldKey; label: string; placeholder: string; span?: string }[] = [
  { key: "legal_name", label: "Legal business name", placeholder: "e.g. Anril Bakes Pvt Ltd", span: "sm:col-span-2" },
  { key: "address", label: "Address", placeholder: "Street, area", span: "sm:col-span-2" },
  { key: "city", label: "City", placeholder: "e.g. Coimbatore" },
  { key: "state", label: "State", placeholder: "e.g. Tamil Nadu" },
  { key: "pincode", label: "Pincode", placeholder: "e.g. 641001" },
  { key: "email", label: "Email", placeholder: "billing@yourbusiness.com" },
  { key: "phone", label: "Phone", placeholder: "e.g. 9876543210" },
];

export default function AccountSettingsPage() {
  const { fullName, initials, email, memberSince, canManageSettings } = useSettingsForm();
  const { tenantName } = useAuthRole();

  const [profile, setProfile] = useState<BusinessProfile>(EMPTY);
  const [draft, setDraft] = useState<BusinessProfile>(EMPTY);
  const [isLoading, setIsLoading] = useState(true);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [gstinError, setGstinError] = useState<string | null>(null);

  useEffect(() => {
    api.businessProfile
      .get()
      .then((data) => {
        setProfile(data);
        setDraft(data);
      })
      .catch((err) => {
        toast.error(err instanceof Error ? err.message : "Failed to load business details");
      })
      .finally(() => setIsLoading(false));
  }, []);

  const isDirty = JSON.stringify(draft) !== JSON.stringify(profile);

  function setField(key: FieldKey, value: string) {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }

  function handleGstinChange(value: string) {
    const upper = value.toUpperCase();
    setDraft((prev) => ({ ...prev, gstin: upper }));
    setGstinError(upper.trim() && !GSTIN_PATTERN.test(upper.trim()) ? "Doesn't look like a valid GSTIN" : null);
  }

  async function handleSave() {
    if (!canManageSettings) return;
    const gstin = draft.gstin.trim();
    if (gstin && !GSTIN_PATTERN.test(gstin)) {
      setGstinError("Doesn't look like a valid GSTIN");
      return;
    }
    setSaveState("saving");
    try {
      const saved = await api.businessProfile.save({ ...draft, gstin });
      setProfile(saved);
      setDraft(saved);
      setSaveState("saved");
      toast.success("Business details saved");
      setTimeout(() => setSaveState("idle"), 2000);
    } catch (err) {
      setSaveState("idle");
      toast.error(err instanceof Error ? err.message : "Failed to save business details");
    }
  }

  return (
    <SettingsAccordion defaultOpenId="profile">

      <SettingsSection
        id="profile"
        icon={UserCircle}
        accent="violet"
        title="Your profile"
        description="Who's signed in, and since when."
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
          description="Your legal name, address and GSTIN, used on the monthly export for your auditor."
          dirty={isDirty}
        >
          {isLoading ? (
            <AiraLoader inline className="min-h-[120px]" />
          ) : (
            <div className="space-y-5">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {TEXT_FIELDS.map((field) => (
                  <div key={field.key} className={field.span}>
                    <label className="mb-1.5 block font-label text-[11px] font-bold uppercase tracking-wider text-ink-muted">
                      {field.label}
                    </label>
                    <input
                      value={draft[field.key]}
                      disabled={!canManageSettings}
                      onChange={(e) => setField(field.key, e.target.value)}
                      placeholder={field.placeholder}
                      className="w-full rounded-xl border border-border bg-white px-3 py-2.5 font-body text-sm text-ink outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:cursor-not-allowed disabled:opacity-60"
                    />
                  </div>
                ))}
                <div>
                  <label className="mb-1.5 block font-label text-[11px] font-bold uppercase tracking-wider text-ink-muted">
                    GSTIN
                  </label>
                  <input
                    value={draft.gstin}
                    disabled={!canManageSettings}
                    onChange={(e) => handleGstinChange(e.target.value)}
                    placeholder="e.g. 33AAAAA0000A1Z5"
                    maxLength={15}
                    className="w-full rounded-xl border border-border bg-white px-3 py-2.5 font-mono text-sm uppercase tracking-wide text-ink outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:cursor-not-allowed disabled:opacity-60"
                  />
                  {gstinError && <p className="mt-1 text-xs text-danger">{gstinError}</p>}
                  {!gstinError && (
                    <p className="mt-1 text-xs text-ink-muted">Leave blank if you&apos;re not GST-registered.</p>
                  )}
                </div>
              </div>

              <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-surface-low p-4">
                <div>
                  <p className="font-label text-sm font-semibold text-ink">My prices include GST</p>
                  <p className="mt-1 max-w-md font-body text-xs leading-relaxed text-ink-muted">
                    {draft.prices_include_gst
                      ? "On: a ₹499 price is what the customer pays (tax is inside)."
                      : "Off: GST is added on top at checkout."}
                  </p>
                </div>
                <SwitchPill
                  on={draft.prices_include_gst}
                  disabled={!canManageSettings}
                  onChange={(next) => setDraft((prev) => ({ ...prev, prices_include_gst: next }))}
                  aria-label="Prices include GST"
                />
              </div>
            </div>
          )}

          <SectionFooter status={<SaveStatus state={saveState} dirty={isDirty} />}>
            <SaveButton state={saveState} dirty={isDirty} disabled={!canManageSettings || isLoading || !!gstinError} onClick={handleSave} />
          </SectionFooter>
        </SettingsSection>
      </div>
    </SettingsAccordion>
  );
}
