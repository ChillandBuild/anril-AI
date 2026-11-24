"use client";

import { Crown } from "lucide-react";
import { PasskeySettings } from "@/app/dashboard/profile/PasskeySettings";
import { useAuthRole } from "../../contexts/AuthRoleContext";
import { useSettingsForm } from "../SettingsFormContext";
import ChangePasswordCard from "../ChangePasswordCard";

const CARD = "rounded-2xl border border-border/70 bg-white p-5 shadow-[0_1px_2px_rgba(28,25,23,0.03)]";

export default function YourAccountPage() {
  const { fullName, initials, email, memberSince, canManageSettings } = useSettingsForm();
  const { tenantName } = useAuthRole();

  return (
    <div className="flex flex-col gap-4">
      <section className={CARD}>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary text-sm font-bold text-white shadow-md shadow-primary/20">
            {initials}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-display text-sm font-bold text-ink">{fullName}</span>
              {canManageSettings && (
                <span className="badge-violet inline-flex items-center gap-1 px-2 py-0.5 font-label text-[10px] font-bold uppercase tracking-wider">
                  <Crown size={11} />
                  Admin
                </span>
              )}
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
      </section>

      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-[1_1_380px]">
          <ChangePasswordCard defaultOpen />
        </div>
        <div className="min-w-0 flex-[1_1_380px]">
          <PasskeySettings />
        </div>
      </div>
    </div>
  );
}
