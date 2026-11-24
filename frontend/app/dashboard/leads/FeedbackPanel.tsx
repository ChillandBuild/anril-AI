"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Phone, Settings2, Star } from "lucide-react";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { ConfirmModal } from "@/components/ConfirmModal";
import { SwitchPill } from "@/components/ui/controls";
import { Select } from "@/components/ui/Select";
import { cn } from "@/lib/utils";
import { Pagination, usePagedList } from "@/components/ui/Pagination";
import { PAGE_SIZE } from "@/lib/pagination";
import { feedbackRowTarget, HIGHLIGHT_MS, recentRowId, unhappyRowId } from "./feedbackHighlight";
import {
  averageText,
  feedbackApi,
  feedbackCostText,
  feedbackTemplateStatus,
  lastDaysRange,
  percentText,
  starsText,
  telHref,
  type FeedbackReport,
  type FeedbackRow,
  type FeedbackSettings,
} from "@/lib/customersApi";

const OFFER_MAX = 200;

const RANGES = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

const STATUS_TONE = {
  good: "bg-[#ecfdf3] text-[#067647]",
  wait: "bg-[#fffaeb] text-[#b54708]",
  bad: "bg-[#fef3f2] text-[#b42318]",
  none: "bg-slate-100 text-slate-700",
} as const;

// Soft amber, not green, so it reads as "look here" and not as "good".
const HIGHLIGHT = "bg-[#fff4d6] ring-2 ring-inset ring-[#f0b429]";

const TZ = "Asia/Kolkata";

function whenText(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: TZ });
}

function personName(r: FeedbackRow): string {
  return r.name?.trim() || r.phone || "Customer";
}

function StatCard({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
      <div className="text-sm font-semibold text-[#556274]">{label}</div>
      <div className="mt-1 font-display text-2xl font-bold text-[#0A1528] sm:text-3xl">{value}</div>
      <div className="mt-1 text-xs text-[#556274]">{hint}</div>
    </div>
  );
}

/** Why people were unhappy: one bar per word group, longest first. */
function UnhappyBars({ rows }: { rows: { text: string; count: number }[] }) {
  if (rows.length === 0) return <p className="mt-3 text-sm text-[#556274]">No unhappy reasons in this time. Good.</p>;
  const most = Math.max(...rows.map((r) => r.count), 1);
  return (
    <ul className="mt-3 space-y-2.5">
      {rows.map((r) => (
        <li key={r.text} className="grid grid-cols-[minmax(0,7.5rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate capitalize text-[#0A1528]">{r.text}</span>
          <span className="h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
            <span className="block h-full rounded-full bg-[#f97066]" style={{ width: `${(r.count / most) * 100}%` }} />
          </span>
          <span className="w-6 text-right font-bold tabular-nums text-[#0A1528]">{r.count}</span>
        </li>
      ))}
    </ul>
  );
}

export function FeedbackPanel() {
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("leads.manage");

  const [settings, setSettings] = useState<FeedbackSettings | null>(null);
  const [settingsFailed, setSettingsFailed] = useState(false);
  // "Feedback message" opens the star message and offer. Open by itself while star messages are off.
  const [messageOpen, setMessageOpen] = useState<boolean | null>(null);
  const [offerDraft, setOfferDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmOn, setConfirmOn] = useState(false);
  const [settingUp, setSettingUp] = useState(false);

  const [days, setDays] = useState("30");
  const [report, setReport] = useState<FeedbackReport | null>(null);
  const [reportFailed, setReportFailed] = useState(false);
  const [fixingId, setFixingId] = useState<string | null>(null);

  // The unhappy-customer bell links here with ?fb=<feedback id>: scroll to that row and mark it for a moment.
  const fb = useSearchParams().get("fb");
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const handledFb = useRef<string | null>(null);
  const highlightTimer = useRef<number | undefined>(undefined);

  const loadSettings = useCallback(async () => {
    try {
      const s = await feedbackApi.settings();
      setSettings(s);
      setOfferDraft(s.offer ?? "");
      setSettingsFailed(false);
    } catch {
      setSettingsFailed(true);
    }
  }, []);

  const loadReport = useCallback(async () => {
    try {
      setReport(await feedbackApi.report(lastDaysRange(Number(days))));
      setReportFailed(false);
    } catch {
      setReportFailed(true);
    }
  }, [days]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  useEffect(() => {
    setReport(null);
    void loadReport();
  }, [loadReport]);

  const recentPages = usePagedList(report?.recent ?? [], days);
  const setRecentPage = recentPages.setPage;

  useEffect(() => {
    if (!report || !fb || handledFb.current === fb) return;
    handledFb.current = fb; // once per link, so "Mark fixed" reloading the report does not re-highlight
    const target = feedbackRowTarget(report, fb);
    if (!target) return;
    // Recent shows 25 a page: open the page that holds the row first, then scroll once it is drawn.
    if (target === recentRowId(fb.trim())) {
      const idx = report.recent.findIndex((r) => r.id === fb.trim());
      if (idx >= 0) setRecentPage(Math.floor(idx / PAGE_SIZE) + 1);
    }
    const frame = window.setTimeout(() => {
      const el = document.getElementById(target);
      if (!el) return;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
      setHighlightId(target);
      highlightTimer.current = window.setTimeout(() => setHighlightId(null), HIGHLIGHT_MS);
    }, 50);
    return () => window.clearTimeout(frame);
  }, [report, fb, setRecentPage]);

  useEffect(() => () => window.clearTimeout(highlightTimer.current), []);

  async function save(next: { on: boolean; offer: string }, doneText: string) {
    setSaving(true);
    try {
      const saved = await feedbackApi.saveSettings(next);
      setSettings((cur) => (cur ? { ...cur, ...saved, on: saved.on ?? next.on, offer: saved.offer ?? (next.offer || null) } : cur));
      toast.success(doneText);
      setConfirmOn(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  async function setUpTemplate() {
    setSettingUp(true);
    try {
      const res = await feedbackApi.setupTemplate();
      const status = res.template_status ?? res.status ?? "pending";
      setSettings((cur) => (cur ? { ...cur, template_status: status } : cur));
      toast.success("Sent to Meta. It usually takes a few minutes to a day.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not set up the star message");
    } finally {
      setSettingUp(false);
    }
  }

  async function markFixed(id: string) {
    setFixingId(id);
    try {
      await feedbackApi.markFixed(id);
      toast.success("Marked as fixed");
      await loadReport();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not mark as fixed");
    } finally {
      setFixingId(null);
    }
  }

  const status = feedbackTemplateStatus(settings?.template_status);
  const approved = status.tone === "good";
  const offerChanged = (settings?.offer ?? "") !== offerDraft.trim();
  const cost = feedbackCostText(settings?.cost_per_message_rupees);
  const showMessage = messageOpen ?? !settings?.on;

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 font-display text-lg font-bold text-[#0A1528]">
              <Star size={18} className="text-primary" aria-hidden="true" /> Feedback
            </h2>
            <p className="mt-1 max-w-xl text-sm text-[#556274]">
              A day or two after an order is delivered or a visit, customers get a message and tap 1 to 5 stars. Happy
              ones are sent to your Google review. Unhappy ones are asked what went wrong, and you see them here.
            </p>
          </div>
          <div className="flex items-center gap-2.5">
            {settings && (
              <button
                type="button"
                onClick={() => setMessageOpen(!showMessage)}
                aria-expanded={showMessage}
                className="inline-flex items-center gap-1.5 rounded-xl border border-[#e2e8f0] px-3 py-1.5 text-xs font-bold text-[#0A1528] hover:bg-slate-50"
              >
                <Settings2 size={13} aria-hidden="true" /> Feedback message
              </button>
            )}
            <span className="text-sm font-semibold text-[#0A1528]">{settings?.on ? "On" : "Off"}</span>
            <SwitchPill
              on={Boolean(settings?.on)}
              disabled={!canManage || !settings || saving}
              aria-label="Ask customers for stars"
              onChange={(next) => {
                if (!settings) return;
                if (next) setConfirmOn(true);
                else void save({ on: false, offer: settings.offer ?? "" }, "Star messages are off");
              }}
            />
          </div>
        </div>

        {settingsFailed && (
          <p className="mt-4 rounded-xl bg-[#fef3f2] px-3 py-2.5 text-sm text-[#912018]">
            We couldn&apos;t load the settings.{" "}
            <button type="button" onClick={() => void loadSettings()} className="font-bold underline">Try again</button>
          </p>
        )}

        {settings && showMessage && (
          <div className="mt-4 grid gap-4 border-t border-[#eef2f6] pt-4 md:grid-cols-2">
            <div>
              <div className="text-sm font-bold text-[#0A1528]">The star message</div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className={cn("rounded-full px-2.5 py-1 text-xs font-semibold", STATUS_TONE[status.tone])}>
                  {status.label}
                </span>
                {canManage && !approved && status.tone !== "wait" && (
                  <button
                    type="button"
                    onClick={() => void setUpTemplate()}
                    disabled={settingUp}
                    className="rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-white disabled:opacity-50"
                  >
                    {settingUp ? "Sending to Meta…" : status.tone === "bad" ? "Set up the star message again" : "Set up the star message"}
                  </button>
                )}
              </div>
              <p className="mt-2 text-xs text-[#556274]">
                {approved
                  ? `Ready. Each message costs ${cost.replace(" per message", "")}.`
                  : status.tone === "wait"
                    ? "Meta is checking the message. Nothing is sent until it is approved."
                    : status.tone === "bad"
                      ? "Meta turned the message down. Set it up again to send a fresh copy."
                      : "Meta has to approve the message once before any star message can go out."}
              </p>
            </div>

            <div>
              <label htmlFor="feedback-offer" className="text-sm font-bold text-[#0A1528]">
                Offer for happy customers <span className="font-normal text-[#556274]">(optional)</span>
              </label>
              <textarea
                id="feedback-offer"
                value={offerDraft}
                onChange={(e) => setOfferDraft(e.target.value.slice(0, OFFER_MAX))}
                disabled={!canManage}
                rows={2}
                placeholder="e.g. 10% off your next visit, code THANKS10"
                className="mt-2 w-full rounded-xl border border-[#e2e8f0] px-3 py-2 text-sm text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-slate-50"
              />
              <div className="mt-1 flex items-center justify-between gap-2">
                <span className="text-xs text-[#556274]">
                  {settings.review_link
                    ? "Sent with your Google review link."
                    : "No Google review link yet. Add it in your Orders settings."}
                </span>
                {canManage && (
                  <button
                    type="button"
                    disabled={saving || !offerChanged}
                    onClick={() => void save({ on: settings.on, offer: offerDraft.trim() }, "Offer saved")}
                    className="shrink-0 rounded-lg border border-[#e2e8f0] px-3 py-1.5 text-xs font-bold text-[#0A1528] hover:bg-slate-50 disabled:opacity-40"
                  >
                    Save offer
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-bold text-[#0A1528]">How it&apos;s going</h3>
        <Select
          value={days}
          onChange={setDays}
          size="sm"
          aria-label="Time range"
          className="w-40"
          options={RANGES}
        />
      </div>

      {reportFailed && (
        <p className="rounded-xl bg-[#fef3f2] px-3 py-2.5 text-sm text-[#912018]">
          We couldn&apos;t load the ratings.{" "}
          <button type="button" onClick={() => void loadReport()} className="font-bold underline">Try again</button>
        </p>
      )}

      {!report && !reportFailed && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" aria-busy="true">
          {[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-2xl bg-slate-100" />)}
        </div>
      )}

      {report && (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Average stars"
              value={averageText(report.average)}
              hint={report.answered > 0 ? `from ${report.answered.toLocaleString("en-IN")} ratings` : "no ratings yet"}
            />
            <StatCard
              label="Answered"
              value={percentText(report.answered_pct)}
              hint={`${report.answered.toLocaleString("en-IN")} of ${report.asked.toLocaleString("en-IN")} asked`}
            />
            <StatCard
              label="Unhappy (1-3 ★)"
              value={(report.unhappy ?? report.unhappy_open.length).toLocaleString("en-IN")}
              hint={`${report.unhappy_open.length.toLocaleString("en-IN")} still open`}
            />
            <StatCard
              label="Google reviews"
              value={(report.google_reviews ?? 0).toLocaleString("en-IN")}
              hint="sent from the 4-5 ★ link"
            />
          </div>

          <section className="rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm">
            <h3 className="text-base font-bold text-[#0A1528]">Unhappy and still open</h3>
            {report.unhappy_open.length === 0 ? (
              <p className="mt-3 text-sm text-[#556274]">Nobody is waiting on you. Good.</p>
            ) : (
              <ul className="mt-2 divide-y divide-[#eef2f6]">
                {report.unhappy_open.map((r) => {
                  const tel = telHref(r.phone);
                  return (
                    <li
                      key={r.id}
                      id={unhappyRowId(r.id)}
                      className={cn(
                        "flex scroll-mt-24 flex-col gap-2 rounded-lg py-3 transition-colors motion-reduce:transition-none sm:flex-row sm:items-start sm:justify-between",
                        highlightId === unhappyRowId(r.id) && cn(HIGHLIGHT, "px-2"),
                      )}
                    >
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          {r.lead_id ? (
                            <Link href={`/dashboard/leads/${r.lead_id}`} className="text-sm font-bold text-[#0A1528] hover:text-primary">
                              {personName(r)}
                            </Link>
                          ) : (
                            <span className="text-sm font-bold text-[#0A1528]">{personName(r)}</span>
                          )}
                          <span className="text-sm font-semibold text-[#b54708]">{starsText(r.stars)}</span>
                        </div>
                        <p className="mt-0.5 break-words text-sm text-[#334155]">
                          {r.reason ? `"${r.reason}"` : "Hasn't said what went wrong yet"}
                        </p>
                        <p className="mt-0.5 text-xs text-[#556274]">
                          {[r.staff_name ? `with ${r.staff_name}` : null, whenText(r.asked_at)].filter(Boolean).join(" · ")}
                        </p>
                      </div>
                      <div className="flex shrink-0 gap-2">
                        {tel && (
                          <a
                            href={tel}
                            className="flex items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3.5 py-2 text-xs font-bold text-[#0A1528] hover:bg-slate-50"
                          >
                            <Phone size={13} aria-hidden="true" /> Call
                          </a>
                        )}
                        {canManage && (
                          <button
                            type="button"
                            onClick={() => void markFixed(r.id)}
                            disabled={fixingId === r.id}
                            className="rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-white disabled:opacity-50"
                          >
                            {fixingId === r.id ? "Saving…" : "Mark fixed"}
                          </button>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm">
              <h3 className="text-base font-bold text-[#0A1528]">Why people were unhappy</h3>
              <p className="mt-0.5 text-xs text-[#556274]">The words that came up most in 1 to 3 star answers.</p>
              <UnhappyBars rows={report.unhappy_reasons ?? []} />
            </section>

            <section className="rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm">
              <h3 className="text-base font-bold text-[#0A1528]">Stars by staff</h3>
              {report.by_staff.length === 0 ? (
                <p className="mt-3 text-sm text-[#556274]">Nothing to show yet.</p>
              ) : (
                <ul className="mt-2 space-y-2">
                  {report.by_staff.map((s) => (
                    <li key={s.staff_name ?? "none"} className="flex items-center justify-between gap-3 text-sm">
                      <span className="min-w-0 truncate text-[#0A1528]">{s.staff_name ?? "No one named"}</span>
                      <span className="shrink-0 font-semibold text-[#0A1528]">
                        {averageText(s.avg)} <span className="text-xs font-normal text-[#556274]">({s.count} {s.count === 1 ? "rating" : "ratings"})</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          <section className="rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm">
            <h3 className="text-base font-bold text-[#0A1528]">Recent</h3>
            {report.recent.length === 0 ? (
              <p className="mt-3 text-sm text-[#556274]">No ratings in this time yet.</p>
            ) : (
              <ul className="mt-2 divide-y divide-[#eef2f6]">
                {recentPages.pageItems.map((r) => (
                  <li
                    key={r.id}
                    id={recentRowId(r.id)}
                    className={cn(
                      "flex scroll-mt-24 items-start justify-between gap-3 rounded-lg py-2.5 transition-colors motion-reduce:transition-none",
                      highlightId === recentRowId(r.id) && cn(HIGHLIGHT, "px-2"),
                    )}
                  >
                    <div className="min-w-0">
                      {r.lead_id ? (
                        <Link href={`/dashboard/leads/${r.lead_id}`} className="text-sm font-semibold text-[#0A1528] hover:text-primary">
                          {personName(r)}
                        </Link>
                      ) : (
                        <span className="text-sm font-semibold text-[#0A1528]">{personName(r)}</span>
                      )}
                      {r.reason && <p className="mt-0.5 break-words text-xs text-[#556274]">&quot;{r.reason}&quot;</p>}
                      {r.staff_name && <p className="mt-0.5 text-xs text-[#556274]">with {r.staff_name}</p>}
                      {(r.status === "fixed" || r.review_link_sent) && (
                        <span className="mt-1 inline-flex rounded-full bg-[#ecfdf3] px-2.5 py-0.5 text-[11.5px] font-semibold text-[#067647]">
                          {r.status === "fixed" ? `✓ Fixed${r.fixed_by_name ? ` by ${r.fixed_by_name}` : ""}` : "Google review link sent"}
                        </span>
                      )}
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="text-sm font-semibold text-[#0A1528]">{r.stars ? starsText(r.stars) : "Not answered"}</div>
                      <div className="text-xs text-[#556274]">{whenText(r.answered_at ?? r.asked_at)}</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <Pagination page={recentPages.page} total={recentPages.total} onPageChange={recentPages.setPage} noun="entries" className="-mx-5 -mb-5 mt-3 px-5" />
          </section>
        </>
      )}

      <ConfirmModal
        open={confirmOn}
        onClose={() => setConfirmOn(false)}
        onConfirm={() => void save({ on: true, offer: settings?.offer ?? "" }, "Star messages are on")}
        title="Turn on star messages?"
        description={`Each customer gets one message, ${cost}, a day or two after an order is delivered or a visit. ${
          approved ? "" : "Nothing goes out until Meta approves the star message. "
        }Messages go out between 10 AM and 8 PM.`}
        tone="primary"
        confirmLabel="Turn on"
        loading={saving}
        loadingLabel="Turning on…"
      />
    </div>
  );
}
