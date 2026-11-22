"use client";
import { useState } from "react";
import { Copy, ExternalLink } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { toast } from "sonner";
import { SwitchPill } from "@/components/ui/controls";
import { bookingsApi, type BookingSettings, type BookingSetup } from "@/lib/bookingsApi";
import { RULE_LIMITS, minutesInWords, templateStatusText, validateRules } from "./bookingsLogic";
import { BTN_DANGER, BTN_PRIMARY, BTN_SECONDARY, ConfirmSheet, Field, INPUT_CLS, Notice, errorText } from "./bookingsUi";

/** The public booking link: copy, QR, on/off, the rules, a new link, and the WhatsApp messages. */
export function LinkTab({ setup, canManage, onChanged }: { setup: BookingSetup; canManage: boolean; onChanged: () => void }) {
  const [rules, setRules] = useState<BookingSettings>(setup.settings);
  const [saving, setSaving] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [askNew, setAskNew] = useState(false);
  const [newBusy, setNewBusy] = useState(false);
  const [tplBusy, setTplBusy] = useState(false);
  const problem = validateRules(rules);
  const dirty = JSON.stringify(rules) !== JSON.stringify(setup.settings);
  // Null when the person may not see the link; this tab is for managers, so it is rare.
  const link = setup.link_url;

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      toast.success("Link copied");
    } catch {
      toast.error("Could not copy. Select the link and copy it.");
    }
  }

  async function toggle(on: boolean) {
    setSwitching(true);
    try {
      await bookingsApi.saveSettings({ ...setup.settings, link_on: on });
      setRules((r) => ({ ...r, link_on: on }));
      onChanged();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setSwitching(false);
    }
  }

  async function saveRules() {
    if (problem) return;
    setSaving(true);
    try {
      await bookingsApi.saveSettings(rules);
      toast.success("Rules saved");
      onChanged();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  async function newLink() {
    setNewBusy(true);
    try {
      await bookingsApi.newLink();
      toast.success("New link made. The old one no longer works.");
      setAskNew(false);
      onChanged();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setNewBusy(false);
    }
  }

  async function setupTemplates() {
    setTplBusy(true);
    try {
      await bookingsApi.setupTemplates();
      toast.success("Sent to WhatsApp for approval. This can take a few minutes.");
      onChanged();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setTplBusy(false);
    }
  }

  const num = (key: "days_ahead" | "min_notice_min" | "cancel_cutoff_min" | "no_show_limit") => (e: React.ChangeEvent<HTMLInputElement>) =>
    setRules((r) => ({ ...r, [key]: e.target.value === "" ? Number.NaN : Number(e.target.value) }));
  const show = (n: number) => (Number.isNaN(n) ? "" : String(n));
  const update = templateStatusText(setup.templates.update);
  const reminder = templateStatusText(setup.templates.reminder);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="min-w-0 space-y-4 rounded-2xl border border-[#e8edf2] bg-white p-4 shadow-sm" aria-labelledby="link-h">
        <div className="flex items-center justify-between gap-3">
          <h2 id="link-h" className="font-display text-lg font-bold text-ink">
            Booking link
          </h2>
          {canManage && <SwitchPill on={setup.settings.link_on} onChange={(v) => void toggle(v)} loading={switching} aria-label="Booking link is on" />}
        </div>
        {!setup.settings.link_on && <Notice tone="amber">The link is off. Customers who open it see that bookings are not available.</Notice>}
        <p className="text-sm text-ink-secondary">Share this with customers. They pick a service, a time, and book without calling.</p>
        {!link && <Notice tone="amber">The link is not available to you. Ask the owner or someone who manages bookings.</Notice>}
        {link && (
        <>
        <div className="flex flex-wrap items-center gap-2">
          <input readOnly value={link} aria-label="Booking link" onFocus={(e) => e.currentTarget.select()} className={`${INPUT_CLS} min-w-0 flex-1`} />
          <button type="button" className={BTN_SECONDARY} onClick={() => void copy()}>
            <Copy size={15} aria-hidden /> Copy
          </button>
          <a href={link} target="_blank" rel="noreferrer" className={BTN_SECONDARY}>
            <ExternalLink size={15} aria-hidden /> Open
          </a>
        </div>
        <div className="flex justify-center rounded-xl border border-[#eef2f6] bg-white p-4">
          <QRCodeSVG value={link} size={176} marginSize={2} role="img" aria-label="QR code for the booking link" />
        </div>
        </>
        )}
        {canManage && (
          <div className="border-t border-[#eef2f6] pt-3">
            <button type="button" className={BTN_DANGER} onClick={() => setAskNew(true)}>
              Make a new link
            </button>
            <p className="mt-1 text-xs text-ink-muted">Use this if the link got to the wrong people. The old link stops working at once.</p>
          </div>
        )}
      </section>

      <div className="min-w-0 space-y-4">
        <section className="space-y-3 rounded-2xl border border-[#e8edf2] bg-white p-4 shadow-sm" aria-labelledby="rules-h">
          <h2 id="rules-h" className="font-display text-lg font-bold text-ink">
            Rules
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="How many days ahead" htmlFor="r-days" hint={`Up to ${RULE_LIMITS.days_ahead.max} days.`}>
              <input id="r-days" inputMode="numeric" value={show(rules.days_ahead)} onChange={num("days_ahead")} disabled={!canManage} className={INPUT_CLS} />
            </Field>
            <Field label="Notice needed (minutes)" htmlFor="r-notice" hint={Number.isNaN(rules.min_notice_min) ? undefined : `Nobody can book within ${minutesInWords(rules.min_notice_min)} of now.`}>
              <input id="r-notice" inputMode="numeric" value={show(rules.min_notice_min)} onChange={num("min_notice_min")} disabled={!canManage} className={INPUT_CLS} />
            </Field>
            <Field label="Cancel or move cut-off (minutes)" htmlFor="r-cut" hint={Number.isNaN(rules.cancel_cutoff_min) ? undefined : `Customers can change it until ${minutesInWords(rules.cancel_cutoff_min)} before.`}>
              <input id="r-cut" inputMode="numeric" value={show(rules.cancel_cutoff_min)} onChange={num("cancel_cutoff_min")} disabled={!canManage} className={INPUT_CLS} />
            </Field>
            <Field label="Didn't-comes before an advance" htmlFor="r-ns" hint="After this many, they must pay the advance.">
              <input id="r-ns" inputMode="numeric" value={show(rules.no_show_limit)} onChange={num("no_show_limit")} disabled={!canManage} className={INPUT_CLS} />
            </Field>
          </div>
          <div className="flex items-center justify-between gap-3 rounded-xl border border-[#eef2f6] px-3 py-2">
            <span className="text-sm font-semibold text-ink">One booking per phone per day</span>
            <SwitchPill on={rules.one_per_day} onChange={(v) => setRules((r) => ({ ...r, one_per_day: v }))} disabled={!canManage} aria-label="One booking per phone per day" />
          </div>
          {problem && <Notice tone="amber">{problem}</Notice>}
          {canManage && (
            <button type="button" className={BTN_PRIMARY} onClick={() => void saveRules()} disabled={saving || !dirty || problem !== null}>
              {saving ? "Saving…" : "Save rules"}
            </button>
          )}
        </section>

        <section className="space-y-3 rounded-2xl border border-[#e8edf2] bg-white p-4 shadow-sm" aria-labelledby="msgs-h">
          <h2 id="msgs-h" className="font-display text-lg font-bold text-ink">
            WhatsApp messages
          </h2>
          <p className="text-sm text-ink-secondary">Booking confirmations, changes and reminders go out on WhatsApp. WhatsApp must approve the two messages first.</p>
          <ul className="space-y-1.5 text-sm">
            <li className="flex items-center justify-between gap-3">
              <span className="text-ink">Confirmation and change message</span>
              <span className={update.ready ? "font-semibold text-emerald-700" : "font-semibold text-amber-800"}>{update.text}</span>
            </li>
            <li className="flex items-center justify-between gap-3">
              <span className="text-ink">Reminder message</span>
              <span className={reminder.ready ? "font-semibold text-emerald-700" : "font-semibold text-amber-800"}>{reminder.text}</span>
            </li>
          </ul>
          {canManage && !(update.ready && reminder.ready) && (
            <button type="button" className={BTN_SECONDARY} onClick={() => void setupTemplates()} disabled={tplBusy}>
              {tplBusy ? "Sending…" : "Set up booking messages"}
            </button>
          )}
        </section>
      </div>

      {askNew && (
        <ConfirmSheet
          title="Make a new link?"
          body="The old link and its QR code stop working at once. Anything you already printed or shared with it will show an error."
          confirmLabel="Make a new link"
          tone="danger"
          busy={newBusy}
          onClose={() => setAskNew(false)}
          onConfirm={() => void newLink()}
        />
      )}
    </div>
  );
}
