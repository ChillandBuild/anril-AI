"use client";
import Link from "next/link";
import { ArrowLeft, MessageCircle } from "lucide-react";
import type { ReactNode } from "react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";

/** The frame the three Anril Setup pages share: who may look, a back link and the Test chat button. */
export function useSetupAccess() {
  const { role, permissions, loading } = useAuthRole();
  const has = (p: string) => role === "owner" || permissions.includes(p);
  return { loading, canView: has("knowledge.view") || has("knowledge.manage"), canEdit: has("knowledge.manage"), has };
}

export function SetupShell({ title, intro, children, right }: { title: string; intro: string; children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-4xl space-y-4 px-4 py-6 sm:px-6">
      <Link href="/dashboard/brain" className="inline-flex min-h-9 items-center gap-1.5 font-label text-xs font-bold text-ink-secondary hover:text-ink">
        <ArrowLeft size={14} aria-hidden /> Anril Setup
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-xl font-bold text-ink">{title}</h1>
          <p className="mt-1 font-body text-sm text-ink-secondary">{intro}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {right}
          <Link href="/dashboard/brain?section=test" className="btn-secondary min-h-9">
            <MessageCircle size={14} aria-hidden /> Test chat
          </Link>
        </div>
      </div>
      {children}
    </div>
  );
}

export function NoAccess() {
  return (
    <div className="py-20 text-center">
      <p className="font-body text-sm text-ink-secondary">You do not have access to this page.</p>
    </div>
  );
}
