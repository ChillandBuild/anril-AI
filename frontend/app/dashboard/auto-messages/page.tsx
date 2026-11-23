"use client";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { ActivitySection } from "./ActivitySection";
import { HeaderCounts } from "./HeaderCounts";
import { usePrivateSend } from "./PrivateSend";
import { MessagesSection } from "./MessagesSection";
import { SourcesSection } from "./SourcesSection";

const SECTION_LABEL = "mb-2 px-1 font-label text-[11px] font-bold uppercase tracking-wide text-ink-secondary";

export default function AutoMessagesPage() {
  const { role, permissions, loading } = useAuthRole();
  const privateSend = usePrivateSend();

  const has = (p: string) => role === "owner" || permissions.includes(p);
  const canManage = has("auto_messages.manage");
  const canView = canManage || has("auto_messages.view");

  if (loading) return <div className="m-6 min-h-[320px] animate-pulse rounded-2xl bg-border-subtle" />;

  if (!canView) {
    return (
      <div className="py-20 text-center">
        <p className="font-body text-sm text-ink-secondary">You do not have access to Auto-Messages.</p>
      </div>
    );
  }

  return (
    <div className="w-full min-w-0 space-y-8">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <p className="max-w-2xl font-body text-sm text-ink-secondary">
          When something happens, Anril sends your approved WhatsApp template.
        </p>
        <HeaderCounts />
      </header>

      <section aria-labelledby="your-messages-h">
        <h2 id="your-messages-h" className={SECTION_LABEL}>
          Your messages
        </h2>
        <MessagesSection canManage={canManage} />
      </section>

      <section id="get-customers-in" aria-labelledby="get-customers-h" className="scroll-mt-6">
        <h2 id="get-customers-h" className={SECTION_LABEL}>
          Get customers in
        </h2>
        <SourcesSection canManage={canManage} privateSend={privateSend} />
      </section>

      <section aria-labelledby="activity-h">
        <h2 id="activity-h" className={SECTION_LABEL}>
          Activity
        </h2>
        <ActivitySection privateSend={privateSend} />
      </section>

      <p className="px-1 font-body text-xs text-ink-secondary">
        Approved templates only · sent instantly · replies come to your Inbox
      </p>
    </div>
  );
}
