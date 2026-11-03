"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import useSWR from "swr";
import { CheckCircle2, Circle, Plus, Wallet } from "lucide-react";
import { api, type SmsBalance, type SmsStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { SUPPORT_FALLBACK, balanceLevel, errorStatus, formatCount, formatRupees, friendlyError } from "./helpers";
import { Btn, Card, Empty, Field, LoadError, Modal, Notice, Skeleton, inputCls, textareaCls } from "./ui";
import { usePerm } from "./usePerm";

const CHECKLIST: { key: "dlt" | "pe_tm" | "sender"; label: string }[] = [
  { key: "dlt", label: "DLT registered" },
  { key: "pe_tm", label: "PE–TM binding" },
  { key: "sender", label: "Sender ID" },
];

const CREDIT_MIN = 100;
const CREDIT_MAX = 1_000_000;
const NOTE_MAX = 300;

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

/** Gates (loading, no access, error, off, setup) and the wallet bar shared by every /dashboard/sms page. */
export function SmsShell({ children }: { children: ReactNode }) {
  const { canView, canManage, loading: roleLoading } = usePerm();
  const status = useSWR("sms:status", () => api.sms.status(), { revalidateOnFocus: false });
  const enabled = status.data?.enabled === true;
  const connected = status.data?.connected === true;
  const balance = useSWR(enabled && connected && canView ? "sms:balance" : null, () => api.sms.balance(), {
    revalidateOnFocus: true,
    refreshInterval: 60_000,
    shouldRetryOnError: false,
  });
  const credit = useSWR(enabled && connected && canView ? "sms:credit-requests" : null, () => api.sms.creditRequests(), {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  const [creditOpen, setCreditOpen] = useState(false);
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
  const newestOpen = [...(credit.data?.items ?? [])]
    .filter((r) => r.status === "open")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];

  return (
    <SmsContext.Provider value={ctx}>
      <div className="w-full space-y-4">
        {/* The page title lives in the app header; the wallet bar sits on top of every SMS page. */}
        <div>
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
            <Link
              href="/dashboard/sms/transactions"
              title={level && level !== "ok" ? topUpHint : undefined}
              aria-label={level && level !== "ok" ? `Open SMS transactions. ${topUpHint}` : "Open SMS transactions"}
              className={cn(
                "flex min-w-0 items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm shadow-sm",
                level === "empty"
                  ? "border-[#fecdd3] bg-[#fff1f2] text-[#be123c]"
                  : level === "low"
                    ? "border-[#fde68a] bg-[#fff7e6] text-[#b45309]"
                    : "border-[#e2e8f0] bg-white hover:border-primary/40",
              )}
            >
              <Wallet size={15} className={cn("shrink-0", (level === "ok" || !level) && "text-primary")} />
              {bal ? (
                <span className={cn("min-w-0 font-bold", level === "ok" && "text-[#0A1528]")}>
                  {bal.wallet != null && <>{formatRupees(bal.wallet)} · </>}
                  {formatCount(bal.sms_count)} SMS left
                  {level === "low" && <span className="font-semibold"> · Low</span>}
                  {level === "empty" && <span className="font-semibold"> · Top up needed</span>}
                </span>
              ) : balance.error ? (
                <span className="text-[#64748b]">{balErr === 409 ? "Not connected" : "Balance unavailable"}</span>
              ) : (
                <span className="text-[#94a3b8]">Loading…</span>
              )}
            </Link>
            {canManage && (
              <Btn variant="outline" className="h-9" onClick={() => setCreditOpen(true)}>
                <Plus size={14} /> Add credit
              </Btn>
            )}
          </div>
          {newestOpen && (
            <p className="mt-2 text-xs text-[#64748b]">
              {formatRupees(newestOpen.amount)} requested on {requestedOn(newestOpen.created_at)} · waiting
            </p>
          )}
        </div>

        {balance.error && balErr === 409 && (
          <Notice tone="warn">SMS isn&apos;t connected yet. Some details may be missing until setup finishes.</Notice>
        )}

        {children}
      </div>

      <AddCreditModal
        open={creditOpen}
        onClose={() => setCreditOpen(false)}
        onSent={() => {
          setCreditOpen(false);
          void credit.mutate();
        }}
      />
    </SmsContext.Provider>
  );
}

/** "3 Nov", in IST. */
function requestedOn(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
}

function AddCreditModal({ open, onClose, onSent }: { open: boolean; onClose: () => void; onSent: () => void }) {
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function close() {
    if (busy) return;
    setError(null);
    onClose();
  }

  async function submit() {
    if (busy) return;
    const n = Number(amount);
    if (!amount.trim() || !Number.isInteger(n) || n < CREDIT_MIN || n > CREDIT_MAX) {
      setError(`Enter a whole amount between ₹${CREDIT_MIN.toLocaleString("en-IN")} and ₹${CREDIT_MAX.toLocaleString("en-IN")}.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const trimmed = note.trim();
      await api.sms.requestCredit({ amount: n, ...(trimmed ? { note: trimmed } : {}) });
      setAmount("");
      setNote("");
      onSent();
    } catch (err) {
      setError(friendlyError(err, "Couldn't send your request. Try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title="Add credit" onClose={close}>
      <div className="space-y-3">
        <p className="text-sm text-[#64748b]">Tell us how much you want to add. We top up your balance and mark the request done.</p>
        <Field label="Amount (₹)" hint={`₹${CREDIT_MIN.toLocaleString("en-IN")} to ₹${CREDIT_MAX.toLocaleString("en-IN")}`}>
          <input
            className={inputCls}
            type="number"
            inputMode="numeric"
            min={CREDIT_MIN}
            max={CREDIT_MAX}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </Field>
        <Field label="Note (optional)">
          <textarea className={textareaCls} rows={2} maxLength={NOTE_MAX} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        {error && <Notice tone="danger">{error}</Notice>}
        <div className="flex justify-end gap-2">
          <Btn variant="outline" disabled={busy} onClick={close}>
            Cancel
          </Btn>
          <Btn busy={busy} onClick={() => void submit()}>
            Submit request
          </Btn>
        </div>
      </div>
    </Modal>
  );
}
