"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api, type ScheduledTemplate } from "@/lib/api";
import { formatSendTime } from "@/lib/schedule-time";

const UNDO_MS = 6000;

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

/** The templates scheduled for one lead: load, cancel (with Undo) and change the time. */
export function useScheduledTemplates(
  leadId: string,
  { onChanged, enabled = true }: { onChanged?: () => void; enabled?: boolean } = {},
) {
  const [items, setItems] = useState<ScheduledTemplate[]>([]);
  const currentLead = useRef(leadId);
  const changed = useRef(onChanged);
  useEffect(() => {
    changed.current = onChanged;
  });

  const refresh = useCallback(async () => {
    // Listing needs the right to send; without it there is nothing to ask for.
    if (!enabled) return;
    const asked = leadId;
    try {
      const next = await api.leads.scheduledTemplates(asked);
      // An answer for the lead we have since left must not land on the new one.
      if (currentLead.current === asked) setItems(next);
    } catch {
      // Keep what is shown; the next refresh tries again.
    }
  }, [leadId, enabled]);

  useEffect(() => {
    currentLead.current = leadId;
    setItems([]);
    void refresh();
  }, [leadId, refresh]);

  const undo = useCallback(
    async (id: string) => {
      try {
        await api.leads.restoreScheduledTemplate(id);
        toast.success("Back on the schedule.");
      } catch (err) {
        toast.error(messageOf(err, "Couldn't undo that"));
      }
      await refresh();
      changed.current?.();
    },
    [refresh],
  );

  const cancel = useCallback(
    async (id: string) => {
      try {
        await api.leads.cancelScheduledTemplate(id);
      } catch (err) {
        toast.error(messageOf(err, "Couldn't cancel it"));
        await refresh();
        return;
      }
      await refresh();
      changed.current?.();
      toast("Cancelled. It won't be sent.", { duration: UNDO_MS, action: { label: "Undo", onClick: () => void undo(id) } });
    },
    [refresh, undo],
  );

  /** Throws with the server's plain-words message so the caller can show it next to the field. */
  const reschedule = useCallback(
    async (id: string, at: Date) => {
      await api.leads.rescheduleTemplate(id, at.toISOString());
      toast.success(`Moved to ${formatSendTime(at)} IST.`);
      await refresh();
      changed.current?.();
    },
    [refresh],
  );

  return { items, refresh, cancel, reschedule };
}
