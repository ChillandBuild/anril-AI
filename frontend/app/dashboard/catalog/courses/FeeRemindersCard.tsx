"use client";
import { useState } from "react";
import useSWR from "swr";
import { coursesApi } from "@/lib/coursesApi";
import { SwitchPill } from "@/components/ui/controls";
import { BTN_SECONDARY, Notice, errorText } from "@/app/dashboard/bookings/bookingsUi";
import { reminderHelp } from "./coursesLogic";

/** The one switch for fee reminders, plus the button that sends the reminder message to WhatsApp for approval. */
export function FeeRemindersCard({ canManage }: { canManage: boolean }) {
  const { data, mutate, error } = useSWR("courses/fee-reminders", coursesApi.reminders, { revalidateOnFocus: false });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run(job: () => Promise<unknown>) {
    setBusy(true);
    setErr("");
    try {
      await job();
      await mutate();
    } catch (e) {
      setErr(errorText(e, "Could not do that. Try again."));
    } finally {
      setBusy(false);
    }
  }

  if (error) return null; // no orders access, or the tables are not there yet: the card is simply not shown
  const approved = data?.template === "APPROVED" || data?.link_template === "APPROVED";
  const linkMissing = data?.link_template == null || data?.link_template === "REJECTED";
  return (
    <section className="rounded-xl border border-[#e2e8f0] bg-white p-4" aria-label="Fee reminders">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-bold text-ink">Fee reminders</h2>
          <p className="mt-1 text-sm text-ink-secondary">{reminderHelp(data)}</p>
        </div>
        <SwitchPill on={Boolean(data?.enabled)} disabled={!canManage || !data || busy || (!approved && !data?.enabled)}
          onChange={(next) => run(() => coursesApi.setReminders(next))} aria-label="Send fee reminders on WhatsApp" />
      </div>
      {canManage && data && data.template !== "APPROVED" && data.template !== "PENDING" ? (
        <div className="mt-3">
          <button type="button" className={BTN_SECONDARY} disabled={busy} onClick={() => run(coursesApi.submitReminderTemplate)}>
            {busy ? "Sending…" : data.template === "REJECTED" ? "Send the message again" : "Send the message to WhatsApp for approval"}
          </button>
        </div>
      ) : canManage && data && linkMissing ? (
        <div className="mt-3">
          <button type="button" className={BTN_SECONDARY} disabled={busy} onClick={() => run(coursesApi.submitReminderTemplate)}>
            {busy ? "Sending…" : "Also send the version with a pay link for approval"}
          </button>
        </div>
      ) : null}
      {err ? <div className="mt-3"><Notice tone="red">{err}</Notice></div> : null}
    </section>
  );
}
