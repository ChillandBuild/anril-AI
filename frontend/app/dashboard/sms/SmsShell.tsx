"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import { api, type SmsBalance, type SmsStatus } from "@/lib/api";
import { friendlyError } from "./helpers";
import { Card, Empty, LoadError, Skeleton } from "./ui";
import { usePerm } from "./usePerm";

interface SmsContextValue {
  status: SmsStatus;
  balance: SmsBalance | null;
  balanceError: unknown;
  reloadBalance: () => void;
  reloadStatus: () => void;
}

const SmsContext = createContext<SmsContextValue | null>(null);

/** Status + wallet for every SMS page. Only available below SmsShell, which renders children once SMS is ready. */
export function useSms(): SmsContextValue {
  const ctx = useContext(SmsContext);
  if (!ctx) throw new Error("useSms must be used inside SmsShell");
  return ctx;
}

/** Gates (loading, no access, error, off, setup) shared by every /dashboard/sms page. */
export function SmsShell({ children }: { children: ReactNode }) {
  const { canView, loading: roleLoading } = usePerm();
  const status = useSWR("sms:status", () => api.sms.status(), { revalidateOnFocus: false });
  const enabled = status.data?.enabled === true;
  const connected = status.data?.connected === true;
  const balance = useSWR(enabled && connected && canView ? "sms:balance" : null, () => api.sms.balance(), {
    revalidateOnFocus: true,
    refreshInterval: 60_000,
    shouldRetryOnError: false,
  });
  const pathname = usePathname();
  const support = status.data?.support_contact || null;

  const ctx = useMemo<SmsContextValue | null>(
    () =>
      status.data
        ? {
            status: status.data,
            balance: balance.data ?? null,
            balanceError: balance.error,
            reloadBalance: () => void balance.mutate(),
            reloadStatus: () => void status.mutate(),
          }
        : null,
    // mutate fns are stable; data/error are the real inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [status.data, balance.data, balance.error],
  );

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

  if (!connected && pathname !== "/dashboard/sms") {
    // Before the Bulk9 key is set only the Dashboard (checklist + Add credit) works.
    return (
      <SmsContext.Provider value={ctx}>
        <Card className="mx-auto max-w-xl">
          <div className="px-5 py-8">
            <h2 className="font-display text-lg font-bold text-[#0A1528]">Setup in progress</h2>
            <p className="mt-1 text-sm text-[#64748b]">
              {"This opens once your SMS account is ready. Meanwhile you can add credit from the Dashboard."}
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Link
                href="/dashboard/sms"
                className="inline-flex h-10 items-center justify-center rounded-xl border border-primary px-4 text-sm font-bold text-primary hover:bg-primary/5"
              >
                Go to Dashboard
              </Link>
            </div>
            {support && <p className="mt-6 text-xs text-[#64748b]">SMS help: {support}</p>}
          </div>
        </Card>
      </SmsContext.Provider>
    );
  }

  // The page title lives in the app header; the wallet and Add credit live on the Dashboard only.
  return (
    <SmsContext.Provider value={ctx}>
      <div className="w-full space-y-4">{children}</div>
    </SmsContext.Provider>
  );
}
