"use client";
import Link from "next/link";
import { MessageCircle } from "lucide-react";
import type { ReactNode } from "react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";

/** The frame the three Anril Setup pages share: who may look, and the Test chat button. */
export function useSetupAccess() {
  const { role, permissions, loading } = useAuthRole();
  const has = (p: string) => role === "owner" || permissions.includes(p);
  return { loading, canView: has("knowledge.view") || has("knowledge.manage"), canEdit: has("knowledge.manage"), has };
}

/** The page title and subtitle live in the app header. The body starts with one toolbar row: the page's own controls on the left, Test chat on the right. */
export function SetupShell({ toolbar, children }: { toolbar?: ReactNode; children: ReactNode }) {
  return (
    <div className="w-full space-y-4 px-4 py-4 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">{toolbar}</div>
        <Link href="/dashboard/brain?section=test" className="btn-secondary ml-auto min-h-9">
          <MessageCircle size={14} aria-hidden /> Test chat
        </Link>
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
