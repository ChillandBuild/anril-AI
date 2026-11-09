"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ClipboardList, Link2, RefreshCw, ShieldAlert, type LucideIcon } from "lucide-react";
import { toast } from "sonner";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useInstantFormsOverview, useInstantFormsStatus } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { InstantFormRange, InstantFormSummary } from "@/lib/api";
import { cn } from "@/lib/utils";
import { LeadsDownloadButton } from "./LeadsDownloadButton";
import { DatesMenu, TOOLBAR_BUTTON } from "./reportControls";
import {
  FormStatusBadge,
  InstantFormStatCards,
  LoadErrorCard,
  StatCardsSkeleton,
  countText,
  dateTimeText,
  errorMessage,
  inrText,
  localDate,
} from "./instantFormsShared";

const PRIMARY_BUTTON =
  "inline-flex h-9 items-center justify-center gap-1.5 rounded-xl bg-primary px-4 font-label text-xs font-bold text-white shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-40";

const COLUMNS: { label: string; right?: boolean }[] = [
  { label: "Form" },
  { label: "Leads", right: true },
  { label: "Cost per lead", right: true },
  { label: "WhatsApp template" },
  { label: "Sent", right: true },
  { label: "Replied", right: true },
  { label: "Last lead" },
];

/** The centred card for each setup step (connect, permission, turn on). */
function SetupCard({
  icon: Icon,
  title,
  children,
  footer,
}: {
  icon: LucideIcon;
  title: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <section className="flex flex-col items-center rounded-2xl border border-[#e2e8f0] bg-white px-6 py-14 text-center shadow-sm">
      <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-50">
        <Icon size={24} className="text-primary-500" aria-hidden="true" />
      </div>
      <h2 className="mb-1 text-base font-bold text-[#1e293b]">{title}</h2>
      <div className="mb-5 max-w-md font-body text-sm leading-relaxed text-[#94a3b8]">{children}</div>
      {footer}
    </section>
  );
}

function FormRow({ form, onOpen }: { form: InstantFormSummary; onOpen: () => void }) {
  return (
    <tr
      tabIndex={0}
      title="Open this form"
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter") onOpen();
      }}
      className="group cursor-pointer transition-colors hover:bg-[#f8fafc] focus:bg-[#f8fafc] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary-200"
    >
      <td className="min-w-[240px] max-w-[320px] px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="min-w-0 truncate font-label text-[13px] font-bold text-[#0A1528] group-hover:text-primary-700" title={form.name}>
            {form.name}
          </span>
          <FormStatusBadge status={form.status} />
        </div>
        {form.ad_names && form.ad_names.length > 0 && (
          <div className="mt-0.5 truncate font-body text-[11px] text-[#475569]" title={form.ad_names.join(", ")}>
            {form.ad_names.length === 1 ? "Ad" : "Ads"}: <span className="font-semibold text-[#0A1528]">{form.ad_names.join(", ")}</span>
          </div>
        )}
        {!form.ad_names?.length && form.past_ad_names && form.past_ad_names.length > 0 && (
          <div
            className="mt-0.5 truncate font-body text-[11px] text-[#475569]"
            title={`No ad uses this form now. Its leads came from: ${form.past_ad_names.join(", ")}`}
          >
            {form.past_ad_names.length === 1 ? "Ad" : "Ads"} (before):{" "}
            <span className="font-semibold text-[#0A1528]">{form.past_ad_names.join(", ")}</span>
          </div>
        )}
        <div className="mt-0.5 font-body text-[11px] text-[#94a3b8]">
          {form.questions} {form.questions === 1 ? "question" : "questions"}
        </div>
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-right text-xs font-semibold tabular-nums text-on-surface">
        {countText(form.leads)}
        <LeadsDownloadButton
          label="Download every lead on this form"
          download={() => api.instantForms.downloadFormLeads(form.form_id, form.name)}
        />
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-right text-xs tabular-nums">{inrText(form.cost_per_lead)}</td>
      <td className="max-w-[220px] px-4 py-3 text-xs">
        {form.template_name ? (
          <span className="block truncate font-label font-semibold text-[#0A1528]" title={form.template_name}>{form.template_name}</span>
        ) : (
          <span className="inline-flex rounded-full bg-amber-50 px-2 py-0.5 font-label text-[11px] font-bold text-amber-800">Not set</span>
        )}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-right text-xs tabular-nums">{countText(form.template_sent)}</td>
      <td className="whitespace-nowrap px-4 py-3 text-right text-xs tabular-nums">{countText(form.replied)}</td>
      <td className="whitespace-nowrap px-4 py-3 text-xs text-on-surface-muted">{dateTimeText(form.last_lead_at)}</td>
    </tr>
  );
}

export function InstantFormsTab() {
  const router = useRouter();
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("meta_ads.manage");
  const [dateFrom, setDateFrom] = useState(() => localDate(29));
  const [dateTo, setDateTo] = useState(() => localDate());
  const [turningOn, setTurningOn] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const { data: status, error: statusError, mutate: mutateStatus } = useInstantFormsStatus();
  const showOverview = status?.state === "ready" && status.subscribed && status.forms > 0;
  const range: InstantFormRange = { date_from: dateFrom, date_to: dateTo };
  const { data: overview, error: overviewError, mutate: mutateOverview } = useInstantFormsOverview(
    showOverview ? range : null,
  );

  async function handleTurnOn() {
    setTurningOn(true);
    try {
      const result = await api.instantForms.connect();
      toast.success(`Found ${result.forms} form(s). Importing past leads — this can take a minute.`);
      await Promise.all([mutateStatus(), mutateOverview()]);
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setTurningOn(false);
    }
  }

  async function handleSync() {
    setSyncing(true);
    try {
      const result = await api.instantForms.sync();
      toast.success(`Synced. ${result.forms} form(s) checked.`);
      await mutateOverview();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setSyncing(false);
    }
  }

  function openForm(formId: string) {
    router.push(`/dashboard/meta-ads/instant-forms/${encodeURIComponent(formId)}`);
  }

  function renderSetup() {
    if (!status) {
      return statusError ? (
        <LoadErrorCard title="Could not load instant forms" message={errorMessage(statusError)} onRetry={() => mutateStatus()} />
      ) : (
        <div className="space-y-[18px]" aria-hidden="true">
          <div className="h-10 w-64 animate-pulse rounded-xl bg-stone-200/70" />
          <StatCardsSkeleton />
        </div>
      );
    }
    if (status.state === "no_page") {
      return (
        <SetupCard
          icon={Link2}
          title="Connect your Facebook Page"
          footer={
            <Link href="/dashboard/settings/connect-channels" className={PRIMARY_BUTTON}>
              Connect Page
            </Link>
          }
        >
          Instant form leads come from the Facebook Page your ads run from. Connect it first.
        </SetupCard>
      );
    }
    if (status.state === "needs_permission" || status.state === "needs_reconnect") {
      return (
        <SetupCard
          icon={ShieldAlert}
          title="Allow Anril to read your form leads"
          footer={
            <>
              <Link href="/dashboard/settings/connect-channels" className={PRIMARY_BUTTON}>
                Reconnect Facebook
              </Link>
              {status.message && (
                <p className="mt-3 max-w-md font-body text-[11px] text-[#94a3b8]">Meta says: {status.message}</p>
              )}
            </>
          }
        >
          Reconnect Facebook and tick every permission Meta asks for, including access to leads. Your Page admin can do this in a minute.
        </SetupCard>
      );
    }
    if (status.state === "error") {
      return (
        <LoadErrorCard
          title="Instant forms are not available right now"
          message={status.message ?? "Something went wrong. Try again in a moment."}
          onRetry={() => mutateStatus()}
        />
      );
    }
    if (!status.subscribed || status.forms === 0) {
      return (
        <SetupCard
          icon={ClipboardList}
          title="Turn on Instant form leads"
          footer={
            canManage ? (
              <button type="button" onClick={handleTurnOn} disabled={turningOn} className={PRIMARY_BUTTON}>
                {turningOn ? "Turning on…" : "Turn on"}
              </button>
            ) : (
              <p className="font-label text-xs font-bold text-[#475569]">Ask an admin to turn this on</p>
            )
          }
        >
          Anril will receive every new form lead the moment it&apos;s submitted, send your WhatsApp template, and import the last 90 days of leads to view here.
        </SetupCard>
      );
    }
    return renderMain();
  }

  function renderMain() {
    return (
      <div className="space-y-[18px]">
        <div className="flex flex-wrap items-center gap-2">
          <DatesMenu
            dateFrom={dateFrom}
            dateTo={dateTo}
            onChange={(from, to) => {
              setDateFrom(from);
              setDateTo(to);
            }}
            canManage={canManage}
            onHistorySaved={() => mutateOverview()}
            historyNote="Spend comes from the same Meta ad data as All ads."
          />
          <span className="flex items-center gap-2 font-label text-xs font-semibold text-[#475569]">
            <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
            Live — new leads arrive instantly
          </span>
          <span className="hidden flex-1 md:block" />
          {canManage && (
            <button
              type="button"
              onClick={handleSync}
              disabled={syncing}
              title="Re-read your forms and pick up any lead from the last two days"
              className={cn(TOOLBAR_BUTTON, "ml-auto md:ml-0")}
            >
              <RefreshCw size={13} className={syncing ? "animate-spin" : ""} />
              {syncing ? "Syncing…" : "Sync forms"}
            </button>
          )}
        </div>

        {overviewError && !overview ? (
          <LoadErrorCard title="Could not load your forms" message={errorMessage(overviewError)} onRetry={() => mutateOverview()} />
        ) : (
          <>
            <InstantFormStatCards
              stats={overview?.totals}
              spendAvailable={overview?.spend_available}
              leadsExtra={{ label: "Forms", value: overview?.forms.length }}
            />
            <section aria-label="Instant forms" className="overflow-hidden rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
              {overview && overview.forms.length === 0 ? (
                <p className="px-4 py-16 text-center font-body text-sm text-[#94a3b8]">No instant forms on this Page yet.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[860px]">
                    <thead>
                      <tr className="border-b border-[#eef2f6]">
                        {COLUMNS.map((column) => (
                          <th
                            key={column.label}
                            className={cn(
                              "whitespace-nowrap px-4 py-3 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted",
                              column.right ? "text-right" : "text-left",
                            )}
                          >
                            {column.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#f1f5f9]">
                      {overview
                        ? overview.forms.map((form) => (
                            <FormRow key={form.form_id} form={form} onOpen={() => openForm(form.form_id)} />
                          ))
                        : Array.from({ length: 4 }, (_, index) => (
                            <tr key={index}>
                              {COLUMNS.map((column) => (
                                <td key={column.label} className="px-4 py-3">
                                  <div className="h-3 w-full max-w-[120px] animate-pulse rounded bg-stone-200/70" />
                                </td>
                              ))}
                            </tr>
                          ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    );
  }

  return <div>{renderSetup()}</div>;
}
