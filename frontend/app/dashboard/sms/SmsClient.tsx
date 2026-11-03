"use client";

import { useState } from "react";
import useSWR from "swr";
import { CheckCircle2, Circle, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { BalanceTab } from "./BalanceTab";
import { CampaignsTab } from "./CampaignsTab";
import { ContactsTab } from "./ContactsTab";
import { DeveloperTab } from "./DeveloperTab";
import { SUPPORT_FALLBACK, balanceLevel, errorStatus, formatCount, formatRupees, friendlyError } from "./helpers";
import { ReportsTab } from "./ReportsTab";
import { TemplatesTab } from "./TemplatesTab";
import { Card, Empty, LoadError, Notice, Skeleton } from "./ui";
import { usePerm } from "./usePerm";

type TabKey = "campaigns" | "contacts" | "templates" | "reports" | "balance" | "developer";

const TABS: { key: TabKey; label: string }[] = [
  { key: "campaigns", label: "Campaigns" },
  { key: "contacts", label: "Contacts" },
  { key: "templates", label: "Templates" },
  { key: "reports", label: "Reports" },
  { key: "balance", label: "Balance" },
  { key: "developer", label: "OTP & Developer" },
];

const CHECKLIST: { key: "dlt" | "pe_tm" | "sender"; label: string }[] = [
  { key: "dlt", label: "DLT registered" },
  { key: "pe_tm", label: "PE–TM binding" },
  { key: "sender", label: "Sender ID" },
];

export function SmsClient() {
  const { canView, loading: roleLoading } = usePerm();
  const [tab, setTab] = useState<TabKey>("campaigns");
  const status = useSWR("sms:status", () => api.sms.status(), { revalidateOnFocus: false });
  const enabled = status.data?.enabled === true;
  const connected = status.data?.connected === true;
  const balance = useSWR(enabled && connected && canView ? "sms:balance" : null, () => api.sms.balance(), {
    revalidateOnFocus: true,
    shouldRetryOnError: false,
  });
  const support = status.data?.support_contact || null;

  if (roleLoading || (status.isLoading && !status.data)) {
    return (
      <div className="w-full space-y-4">
        <Skeleton className="h-16" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (!canView) {
    return (
      <Card>
        <Empty title="You don't have access to SMS." hint="Ask the account owner to give your role SMS access." />
      </Card>
    );
  }

  if (status.error && !status.data) {
    // 403 on /status would mean the user is not a tenant member at all; treat everything as a load error.
    return (
      <Card>
        <LoadError message={friendlyError(status.error, "Check your connection and try again.")} onRetry={() => void status.mutate()} />
      </Card>
    );
  }

  if (!enabled) {
    return (
      <Card>
        <Empty
          title="SMS isn't turned on for your account."
          hint={support ? `Contact ${support} to get it switched on.` : "Contact support to get it switched on."}
        />
      </Card>
    );
  }

  if (!connected) {
    const checklist = status.data?.checklist;
    return (
      <Card className="mx-auto max-w-xl">
        <div className="px-5 py-8">
          <h1 className="font-display text-xl font-bold text-[#0A1528]">Setup in progress</h1>
          <p className="mt-1 text-sm text-[#64748b]">
            {"We're getting your SMS account ready. You'll be able to send as soon as these are done."}
          </p>
          <ul className="mt-5 space-y-2.5">
            {CHECKLIST.map((item) => {
              const done = checklist?.[item.key] === true;
              return (
                <li key={item.key} className="flex items-center gap-2.5 text-sm">
                  {done ? <CheckCircle2 size={18} className="text-success" /> : <Circle size={18} className="text-[#cbd5e1]" />}
                  <span className={done ? "font-semibold text-[#0A1528]" : "text-[#64748b]"}>{item.label}</span>
                </li>
              );
            })}
          </ul>
          {support && <p className="mt-6 text-xs text-[#64748b]">SMS help: {support}</p>}
        </div>
      </Card>
    );
  }

  const bal = balance.data;
  const balErr = balance.error ? errorStatus(balance.error) : undefined;

  const level = bal ? balanceLevel(bal.sms_count) : null;
  const topUpHint = `Contact ${support ?? SUPPORT_FALLBACK} to top up.`;

  return (
    <div className="w-full space-y-4">
      {/* The page title lives in the app header; the balance chip sits on the tab row. */}
      <div className="flex items-center gap-3 border-b border-[#e2e8f0]">
        <div className="-mx-1 min-w-0 flex-1 overflow-x-auto px-1">
          <div role="tablist" className="flex min-w-max gap-1">
            {TABS.map((t) => (
              <button
                key={t.key}
                role="tab"
                type="button"
                aria-selected={tab === t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  "-mb-px whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-bold transition-colors",
                  tab === t.key ? "border-primary text-primary" : "border-transparent text-[#64748b] hover:text-[#0A1528]",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
        <button
          type="button"
          onClick={() => setTab("balance")}
          title={level && level !== "ok" ? topUpHint : undefined}
          className={cn(
            "mb-1.5 flex shrink-0 items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm shadow-sm",
            level === "empty"
              ? "border-[#fecdd3] bg-[#fff1f2] text-[#be123c]"
              : level === "low"
                ? "border-[#fde68a] bg-[#fff7e6] text-[#b45309]"
                : "border-[#e2e8f0] bg-white hover:border-primary/40",
          )}
          aria-label={level && level !== "ok" ? `Open SMS balance. ${topUpHint}` : "Open SMS balance"}
        >
          <Wallet size={15} className={level === "ok" || !level ? "text-primary" : undefined} />
          {bal ? (
            <span className={cn("font-bold", level === "ok" && "text-[#0A1528]")}>
              {formatCount(bal.sms_count)} SMS
              {bal.wallet != null && <span className="font-semibold"> · {formatRupees(bal.wallet)}</span>}
              {level === "low" && <span className="font-semibold"> · Low</span>}
              {level === "empty" && <span className="font-semibold"> · Top up needed</span>}
            </span>
          ) : balance.error ? (
            <span className="text-[#64748b]">{balErr === 409 ? "Not connected" : "Balance unavailable"}</span>
          ) : (
            <span className="text-[#94a3b8]">Loading…</span>
          )}
        </button>
      </div>

      {balance.error && balErr === 409 && (
        <Notice tone="warn">SMS isn&apos;t connected yet. Some details may be missing until setup finishes.</Notice>
      )}

      {tab === "campaigns" && <CampaignsTab onBalanceChanged={() => void balance.mutate()} onOpenTemplates={() => setTab("templates")} />}
      {tab === "contacts" && <ContactsTab />}
      {tab === "templates" && <TemplatesTab />}
      {tab === "reports" && <ReportsTab />}
      {tab === "balance" && <BalanceTab balance={bal ?? null} balanceError={balance.error ? friendlyError(balance.error, "Couldn't load your balance.") : null} onReload={() => void balance.mutate()} />}
      {tab === "developer" && <DeveloperTab onOpenCampaigns={() => setTab("campaigns")} />}
    </div>
  );
}
