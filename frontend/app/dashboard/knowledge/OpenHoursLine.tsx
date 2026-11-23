"use client";

// v9.2 #59: the Description shows the open hours read-only. They live in one place (Settings › Open hours),
// so they are never typed into the description where a second copy would go stale.
import { useEffect, useState } from "react";
import Link from "next/link";
import { Clock } from "lucide-react";
import { openHoursApi, type OpenHours } from "@/lib/replySettingsApi";

export function OpenHoursLine() {
  const [hours, setHours] = useState<OpenHours | null>(null);
  useEffect(() => {
    openHoursApi.get().then(setHours).catch(() => setHours(null)); // no settings.view: show nothing
  }, []);
  if (!hours) return null;
  return (
    <section aria-label="Open hours" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl border border-border-subtle bg-surface-low px-4 py-3">
      <Clock size={16} className="shrink-0 text-primary" aria-hidden="true" />
      {hours.set ? (
        <p className="min-w-0 flex-1 font-body text-sm text-ink">
          <span className="font-semibold">Open hours: {hours.summary}</span>
          <span className="text-ink-muted"> · The AI reads these from Settings, so leave hours out of the description.</span>
        </p>
      ) : (
        <p className="min-w-0 flex-1 font-body text-sm text-ink">
          <span className="font-semibold">Open hours are not set.</span>
          <span className="text-ink-muted"> Set them once and the AI tells customers when you are open.</span>
        </p>
      )}
      <Link href="/dashboard/settings/business-hours" className="font-label text-sm font-bold text-primary underline">
        {hours.set ? "Change" : "Set open hours"}
      </Link>
    </section>
  );
}
