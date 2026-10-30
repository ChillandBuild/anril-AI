"use client";
import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { toast } from "sonner";
import {
  createOperatorSmsAccount,
  creditOperatorSms,
  debitOperatorSms,
  disableOperatorSms,
  enableOperatorSms,
  getOperatorSms,
  patchOperatorSmsSettings,
  putOperatorSmsKey,
  registerOperatorSmsWebhook,
  retryOperatorSmsCredit,
  rupees,
  updateOperatorSmsTemplateRequest,
  type OperatorSms,
  type OperatorSmsChecklist,
  type OperatorSmsPayment,
  type OperatorSmsTemplateRequest,
} from "@/lib/operator";
import { ConfirmModal } from "@/components/ConfirmModal";
import { OperatorToggle } from "../../../components/operator-toggle";
import { SmsStockCard } from "../../../components/sms-stock-card";
import { SkeletonCard } from "../components/skeleton";

const inputCls =
  "w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-primary disabled:opacity-60";
const btnCls =
  "inline-flex items-center justify-center gap-1.5 rounded-full bg-primary px-4 py-2 font-label text-xs font-bold text-white shadow-sm transition-all hover:bg-primary/90 disabled:opacity-50";
const cardCls = "rounded-card border border-border bg-white p-4 shadow-sm";

const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);
const istDate = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })
    : "—";

function Badge({ ok, yes, no }: { ok: boolean; yes: string; no: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${ok ? "bg-green-50 text-success" : "bg-red-50 text-danger"}`}>
      {ok ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
      {ok ? yes : no}
    </span>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-ink-muted">{label}</span>
      {children}
    </label>
  );
}

function Busy({ on, children }: { on: boolean; children: React.ReactNode }) {
  return on ? <Loader2 size={13} className="animate-spin" /> : <>{children}</>;
}

export function SmsView({ tenantId }: { tenantId: string }) {
  const [data, setData] = useState<OperatorSms | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await getOperatorSms(tenantId));
      setLoadError(null);
    } catch (e) {
      setLoadError(errText(e, "Failed to load SMS"));
    }
  }, [tenantId]);
  useEffect(() => { load(); }, [load]);

  /** Run a mutation that returns the fresh OperatorSms; show API detail on failure. */
  async function run(key: string, fn: () => Promise<OperatorSms>, okMsg: string): Promise<boolean> {
    setBusy(key);
    try {
      setData(await fn());
      toast.success(okMsg);
      return true;
    } catch (e) {
      toast.error(errText(e, "Request failed"));
      return false;
    } finally {
      setBusy(null);
    }
  }

  if (loadError && !data) {
    return <div className="rounded-xl border border-danger/20 bg-red-50 p-4 text-sm text-danger">{loadError}</div>;
  }
  if (!data) {
    return <div className="grid grid-cols-2 gap-4"><SkeletonCard /><SkeletonCard /></div>;
  }

  return (
    <div className="space-y-6">
      <SmsStockCard />
      <StatusHeader tenantId={tenantId} data={data} busy={busy} run={run} />
      <AccountStep tenantId={tenantId} data={data} busy={busy} run={run} />
      <KeyStep tenantId={tenantId} data={data} busy={busy} run={run} />
      <ChecklistStep tenantId={tenantId} data={data} busy={busy} run={run} />
      <PricingCard tenantId={tenantId} data={data} busy={busy} run={run} />
      <BalanceAndProfit data={data} />
      <CreditDebit tenantId={tenantId} data={data} busy={busy} run={run} />
      <LedgerTable data={data} />
      <RechargesTable tenantId={tenantId} payments={data.payments ?? []} busy={busy} run={run} />
      <TemplateRequests tenantId={tenantId} requests={data.template_requests} busy={busy} run={run} />
    </div>
  );
}

type RunFn = (key: string, fn: () => Promise<OperatorSms>, okMsg: string) => Promise<boolean>;
type SectionProps = { tenantId: string; data: OperatorSms; busy: string | null; run: RunFn };

function StatusHeader({ tenantId, data, busy, run }: SectionProps) {
  return (
    <div className={cardCls}>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <p className="text-sm font-semibold text-ink">SMS (Bulk9)</p>
          <div className="flex flex-wrap items-center gap-2">
            <Badge ok={data.enabled} yes="Enabled" no="Disabled" />
            <Badge ok={data.connected} yes="Connected" no="Not connected" />
            <Badge ok={data.webhook_registered} yes="Webhook registered" no="Webhook not registered" />
            <span className="text-xs text-ink-muted">Bulk9 username: <b className="text-ink">{data.bulk9_username ?? "—"}</b></span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            className={btnCls}
            disabled={busy === "webhook" || !data.connected}
            onClick={() => run("webhook", () => registerOperatorSmsWebhook(tenantId), "Webhook registered.")}
          >
            <Busy on={busy === "webhook"}>Re-register webhook</Busy>
          </button>
          <OperatorToggle
            checked={data.enabled}
            loading={busy === "toggle"}
            aria-label="Toggle SMS"
            onChange={() =>
              run(
                "toggle",
                () => (data.enabled ? disableOperatorSms(tenantId) : enableOperatorSms(tenantId)),
                data.enabled ? "SMS disabled." : "SMS enabled.",
              )
            }
          />
        </div>
      </div>
    </div>
  );
}

function AccountStep({ tenantId, data, busy, run }: SectionProps) {
  const [f, setF] = useState({ username: "", name: "", email: "", mobile: "" });
  const [linked, setLinked] = useState(data.bulk9_username ?? "");
  const hasUser = !!data.bulk9_username;
  return (
    <div className={cardCls}>
      <p className="text-sm font-semibold text-ink">Step 1 — Bulk9 account</p>
      {!hasUser ? (
        <>
          <p className="mt-1 text-xs text-ink-muted">Creates a Bulk9 user under your reseller account. To link one that already exists, enter only the username below and save it.</p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <Field label="Username"><input className={inputCls} value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} placeholder="brightpath" /></Field>
            <Field label="Name"><input className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Email (optional)"><input className={inputCls} type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
            <Field label="Mobile (optional)"><input className={inputCls} inputMode="tel" value={f.mobile} onChange={(e) => setF({ ...f, mobile: e.target.value })} /></Field>
          </div>
          <div className="mt-3 flex gap-3">
            <button
              type="button"
              className={btnCls}
              disabled={busy === "account" || !f.username.trim() || !f.name.trim()}
              onClick={() =>
                run("account", () => createOperatorSmsAccount(tenantId, {
                  username: f.username.trim(),
                  name: f.name.trim(),
                  ...(f.email.trim() ? { email: f.email.trim() } : {}),
                  ...(f.mobile.trim() ? { mobile: f.mobile.trim() } : {}),
                }), "Bulk9 account created.")
              }
            >
              <Busy on={busy === "account"}>Create Bulk9 account</Busy>
            </button>
            <button
              type="button"
              className="rounded-full border border-border px-4 py-2 font-label text-xs font-bold text-ink hover:bg-surface-mid disabled:opacity-50"
              disabled={busy === "link" || !f.username.trim()}
              onClick={() => run("link", () => patchOperatorSmsSettings(tenantId, { bulk9_username: f.username.trim() }), "Username linked.")}
            >
              <Busy on={busy === "link"}>Link existing username</Busy>
            </button>
          </div>
        </>
      ) : (
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div className="w-64">
            <Field label="Bulk9 username (edit to link a different account)">
              <input className={inputCls} value={linked} onChange={(e) => setLinked(e.target.value)} />
            </Field>
          </div>
          <button
            type="button"
            className={btnCls}
            disabled={busy === "link" || !linked.trim() || linked.trim() === data.bulk9_username}
            onClick={() => run("link", () => patchOperatorSmsSettings(tenantId, { bulk9_username: linked.trim() }), "Username saved.")}
          >
            <Busy on={busy === "link"}>Save</Busy>
          </button>
        </div>
      )}
    </div>
  );
}

function KeyStep({ tenantId, data, busy, run }: SectionProps) {
  const [key, setKey] = useState("");
  return (
    <div className={cardCls}>
      <p className="text-sm font-semibold text-ink">Step 2 — Client key</p>
      <p className="mt-1 text-xs text-ink-muted">
        Copy from Bulk9 → Login as User → Dev API. Saving tests the wallet and registers the delivery webhook.
        {data.key_masked && <> Current key: <b className="text-ink">{data.key_masked}</b></>}
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div className="w-96 max-w-full">
          <Field label={data.key_masked ? "Replace key" : "API key"}>
            <input type="password" autoComplete="off" className={inputCls} value={key} onChange={(e) => setKey(e.target.value)} />
          </Field>
        </div>
        <button
          type="button"
          className={btnCls}
          disabled={busy === "key" || !key.trim()}
          onClick={async () => { if (await run("key", () => putOperatorSmsKey(tenantId, key.trim()), "Key saved and tested.")) setKey(""); }}
        >
          <Busy on={busy === "key"}>Save key</Busy>
        </button>
      </div>
    </div>
  );
}

const CHECKS: { key: keyof OperatorSmsChecklist; label: string }[] = [
  { key: "dlt", label: "DLT registered" },
  { key: "pe_tm", label: "PE–TM binding done" },
  { key: "sender", label: "Sender ID added" },
];

function ChecklistStep({ tenantId, data, busy, run }: SectionProps) {
  return (
    <div className={cardCls}>
      <p className="text-sm font-semibold text-ink">Step 3 — Checklist</p>
      <p className="mt-1 text-xs text-ink-muted">Bulk9 has no API for these, so tick them by hand.</p>
      <div className="mt-3 flex flex-wrap gap-6">
        {CHECKS.map((c) => (
          <label key={c.key} className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={data.checklist[c.key]}
              disabled={busy === `check-${c.key}`}
              onChange={(e) =>
                run(`check-${c.key}`, () => patchOperatorSmsSettings(tenantId, { checklist: { ...data.checklist, [c.key]: e.target.checked } }), "Checklist saved.")
              }
            />
            {c.label}
          </label>
        ))}
      </div>
    </div>
  );
}

function PricingCard({ tenantId, data, busy, run }: SectionProps) {
  const [price, setPrice] = useState(data.price_per_sms?.toString() ?? "");
  const [buy, setBuy] = useState(data.buy_rate?.toString() ?? "");
  const [support, setSupport] = useState(data.support_contact ?? "");
  const p = price.trim() === "" ? undefined : Number(price);
  const b = buy.trim() === "" ? undefined : Number(buy);
  const invalid = (p !== undefined && !(p >= 0)) || (b !== undefined && !(b >= 0));
  return (
    <div className={cardCls}>
      <p className="text-sm font-semibold text-ink">Pricing</p>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <Field label="Client price per SMS (₹)">
          <input className={inputCls} type="number" step="0.0001" min="0" value={price} onChange={(e) => setPrice(e.target.value)} />
        </Field>
        <Field label="Your buy rate per SMS (₹)">
          <input className={inputCls} type="number" step="0.0001" min="0" value={buy} onChange={(e) => setBuy(e.target.value)} />
        </Field>
        <Field label="Support contact (shown to client)">
          <input className={inputCls} value={support} onChange={(e) => setSupport(e.target.value)} placeholder="phone or email" />
        </Field>
      </div>
      <p className="mt-2 text-xs text-ink-muted">
        Now: {rupees(data.price_per_sms, 4)} sold, {rupees(data.buy_rate, 4)} cost per SMS.
      </p>
      <button
        type="button"
        className={`${btnCls} mt-3`}
        disabled={busy === "pricing" || invalid}
        onClick={() =>
          run("pricing", () => patchOperatorSmsSettings(tenantId, {
            ...(p !== undefined ? { price_per_sms: p } : {}),
            ...(b !== undefined ? { buy_rate: b } : {}),
            support_contact: support.trim(),
          }), "Pricing saved.")
        }
      >
        <Busy on={busy === "pricing"}>Save pricing</Busy>
      </button>
    </div>
  );
}

function BalanceAndProfit({ data }: { data: OperatorSms }) {
  const pr = data.profit;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className={cardCls}>
        <p className="text-sm font-semibold text-ink">Balance</p>
        {data.balance ? (
          <div className="mt-2 flex items-baseline gap-6">
            <p className="text-2xl font-bold text-ink">{rupees(data.balance.wallet)}</p>
            <p className="text-sm text-ink-muted">{data.balance.sms_count.toLocaleString("en-IN")} SMS</p>
          </div>
        ) : (
          <p className="mt-2 text-sm text-danger">{data.balance_error ?? "No balance available yet."}</p>
        )}
      </div>
      <div className={cardCls}>
        <p className="text-sm font-semibold text-ink">Profit</p>
        <dl className="mt-2 grid grid-cols-4 gap-2 text-sm">
          <div><dt className="text-xs text-ink-muted">SMS sold</dt><dd className="font-semibold text-ink">{pr.sms_sold.toLocaleString("en-IN")}</dd></div>
          <div><dt className="text-xs text-ink-muted">Revenue</dt><dd className="font-semibold text-ink">{rupees(pr.revenue)}</dd></div>
          <div><dt className="text-xs text-ink-muted">Cost</dt><dd className="font-semibold text-ink">{rupees(pr.cost)}</dd></div>
          <div><dt className="text-xs text-ink-muted">Profit</dt><dd className={`font-bold ${pr.profit < 0 ? "text-danger" : "text-success"}`}>{rupees(pr.profit)}</dd></div>
        </dl>
      </div>
    </div>
  );
}

function CreditDebit({ tenantId, data, busy, run }: SectionProps) {
  const [kind, setKind] = useState<"manual_credit" | "bonus">("manual_credit");
  const [count, setCount] = useState("");
  const [price, setPrice] = useState("");
  const [expiry, setExpiry] = useState("");
  const [note, setNote] = useState("");
  const [dCount, setDCount] = useState("");
  const [dNote, setDNote] = useState("");
  const [confirmDebit, setConfirmDebit] = useState(false);

  const n = Number(count);
  const dn = Number(dCount);
  const effPrice = price.trim() === "" ? data.price_per_sms : Number(price);

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className={cardCls}>
        <p className="text-sm font-semibold text-ink">Add credit</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Field label="Type">
            <select className={inputCls} value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
              <option value="manual_credit">Manual credit</option>
              <option value="bonus">Bonus</option>
            </select>
          </Field>
          <Field label="SMS count">
            <input className={inputCls} type="number" min="1" step="1" value={count} onChange={(e) => setCount(e.target.value)} />
          </Field>
          <Field label={`Price per SMS (₹, default ${rupees(data.price_per_sms, 4)})`}>
            <input className={inputCls} type="number" min="0" step="0.0001" value={price} onChange={(e) => setPrice(e.target.value)} />
          </Field>
          <Field label="Expiry date (optional)">
            <input className={inputCls} type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} />
          </Field>
        </div>
        <div className="mt-3">
          <Field label="Note"><input className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. free trial, cash payment" /></Field>
        </div>
        {Number.isInteger(n) && n > 0 && effPrice !== null && effPrice !== undefined && (
          <p className="mt-2 text-xs text-ink-muted">Records {n.toLocaleString("en-IN")} SMS worth {rupees(n * effPrice)}.</p>
        )}
        <button
          type="button"
          className={`${btnCls} mt-3`}
          disabled={busy === "credit" || !Number.isInteger(n) || n <= 0 || (price.trim() !== "" && !(Number(price) >= 0))}
          onClick={async () => {
            const ok = await run("credit", () => creditOperatorSms(tenantId, {
              kind,
              sms_count: n,
              ...(price.trim() !== "" ? { price_per_sms: Number(price) } : data.price_per_sms !== null ? { price_per_sms: data.price_per_sms } : {}),
              ...(expiry ? { expiry_date: expiry } : {}),
              ...(note.trim() ? { note: note.trim() } : {}),
            }), "Credit added.");
            if (ok) { setCount(""); setPrice(""); setExpiry(""); setNote(""); }
          }}
        >
          <Busy on={busy === "credit"}>Add credit</Busy>
        </button>
      </div>

      <div className={cardCls}>
        <p className="text-sm font-semibold text-ink">Debit</p>
        <p className="mt-1 text-xs text-ink-muted">Removes SMS from the client&apos;s balance (e.g. a correction).</p>
        <div className="mt-3 space-y-3">
          <Field label="SMS count">
            <input className={inputCls} type="number" min="1" step="1" value={dCount} onChange={(e) => setDCount(e.target.value)} />
          </Field>
          <Field label="Note"><input className={inputCls} value={dNote} onChange={(e) => setDNote(e.target.value)} /></Field>
        </div>
        <button
          type="button"
          className="mt-3 inline-flex items-center justify-center rounded-full bg-danger px-4 py-2 font-label text-xs font-bold text-white shadow-sm hover:bg-danger/90 disabled:opacity-50"
          disabled={busy === "debit" || !Number.isInteger(dn) || dn <= 0}
          onClick={() => setConfirmDebit(true)}
        >
          Debit
        </button>
      </div>

      <ConfirmModal
        open={confirmDebit}
        onClose={() => setConfirmDebit(false)}
        title="Debit SMS?"
        description={`This removes ${dn.toLocaleString("en-IN")} SMS from the client's balance.`}
        confirmLabel="Debit"
        tone="danger"
        loading={busy === "debit"}
        onConfirm={async () => {
          const ok = await run("debit", () => debitOperatorSms(tenantId, { sms_count: dn, ...(dNote.trim() ? { note: dNote.trim() } : {}) }), "Debit recorded.");
          setConfirmDebit(false);
          if (ok) { setDCount(""); setDNote(""); }
        }}
      />
    </div>
  );
}

function LedgerTable({ data }: { data: OperatorSms }) {
  const th = "px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-muted";
  const td = "px-3 py-2 text-sm text-ink";
  return (
    <div className={cardCls}>
      <p className="mb-3 text-sm font-semibold text-ink">Ledger</p>
      {data.ledger.length === 0 ? (
        <p className="text-sm text-ink-muted">No entries yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className={th}>Kind</th><th className={th}>SMS</th><th className={th}>Price</th>
                <th className={th}>Buy rate</th><th className={th}>Amount</th><th className={th}>Expiry</th>
                <th className={th}>Note</th><th className={th}>Date</th>
              </tr>
            </thead>
            <tbody>
              {data.ledger.map((l) => (
                <tr key={l.id} className="border-b border-border last:border-0">
                  <td className={td}>{l.kind.replace(/_/g, " ")}</td>
                  <td className={td}>{l.sms_count.toLocaleString("en-IN")}</td>
                  <td className={td}>{rupees(l.price_per_sms, 4)}</td>
                  <td className={td}>{rupees(l.buy_rate, 4)}</td>
                  <td className={td}>{rupees(l.amount)}</td>
                  <td className={td}>{l.expiry_date ?? "—"}</td>
                  <td className={`${td} max-w-[220px] truncate`} title={l.note ?? ""}>{l.note ?? "—"}</td>
                  <td className={`${td} whitespace-nowrap`}>{istDate(l.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

type ReqStatus = "in_progress" | "ready" | "rejected";


// Paid 10+ minutes ago and still not credited: the server stopped between taking the payment
// and adding the SMS. The backend accepts a retry for these (operator_sms.retry_credit).
const STUCK_PAID_MS = 10 * 60 * 1000;
function stuckPaid(p: OperatorSmsPayment): boolean {
  return p.status === "paid" && !!p.paid_at && Date.now() - new Date(p.paid_at).getTime() > STUCK_PAID_MS;
}
function needsAttention(p: OperatorSmsPayment): boolean {
  return p.status === "credit_failed" || p.status === "amount_mismatch" || stuckPaid(p);
}

function RequestRow({ r, tenantId, busy, run }: { r: OperatorSmsTemplateRequest; tenantId: string; busy: string | null; run: RunFn }) {
  const initial: ReqStatus = r.status === "ready" || r.status === "rejected" ? r.status : "in_progress";
  const [status, setStatus] = useState<ReqStatus>(initial);
  const [reason, setReason] = useState(r.reason ?? "");
  const key = `req-${r.id}`;
  const td = "px-3 py-2 text-sm text-ink align-top";
  return (
    <tr className="border-b border-border last:border-0">
      <td className={`${td} max-w-[320px] whitespace-pre-wrap`}>{r.wording}</td>
      <td className={td}>{r.template_type}</td>
      <td className={td}>
        <select className={inputCls} value={status} onChange={(e) => setStatus(e.target.value as ReqStatus)} aria-label="Request status">
          <option value="in_progress">In progress</option>
          <option value="ready">Ready</option>
          <option value="rejected">Rejected</option>
        </select>
        <p className="mt-1 text-xs text-ink-muted">Currently: {r.status.replace(/_/g, " ")}</p>
      </td>
      <td className={td}>
        <input className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (shown to client)" />
      </td>
      <td className={`${td} whitespace-nowrap`}>{istDate(r.created_at)}</td>
      <td className={td}>
        <button
          type="button"
          className={btnCls}
          disabled={busy === key}
          onClick={() => run(key, () => updateOperatorSmsTemplateRequest(tenantId, r.id, { status, ...(reason.trim() ? { reason: reason.trim() } : {}) }), "Request updated.")}
        >
          <Busy on={busy === key}>Save</Busy>
        </button>
      </td>
    </tr>
  );
}

function TemplateRequests({ tenantId, requests, busy, run }: { tenantId: string; requests: OperatorSmsTemplateRequest[]; busy: string | null; run: RunFn }) {
  const th = "px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-muted";
  return (
    <div className={cardCls}>
      <p className="mb-3 text-sm font-semibold text-ink">Template requests</p>
      {requests.length === 0 ? (
        <p className="text-sm text-ink-muted">No template requests.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className={th}>Wording</th><th className={th}>Type</th><th className={th}>Status</th>
                <th className={th}>Reason</th><th className={th}>Requested</th><th className={th} />
              </tr>
            </thead>
            <tbody>
              {requests.map((r) => (
                <RequestRow key={`${r.id}-${r.updated_at ?? ""}`} r={r} tenantId={tenantId} busy={busy} run={run} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RechargesTable({ tenantId, payments, busy, run }: { tenantId: string; payments: OperatorSmsPayment[]; busy: string | null; run: RunFn }) {
  const [retryId, setRetryId] = useState<string | null>(null);
  const th = "px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-ink-muted";
  const td = "px-3 py-2 text-sm text-ink align-top";
  return (
    <div className={cardCls}>
      <p className="mb-3 text-sm font-semibold text-ink">Recharges</p>
      {payments.length === 0 ? (
        <p className="text-sm text-ink-muted">No recharges yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className={th}>Amount</th><th className={th}>SMS</th><th className={th}>Status</th>
                <th className={th}>Created</th><th className={th}>Credited</th><th className={th} />
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <tr key={p.id} className="border-b border-border last:border-0">
                  <td className={td}>{rupees(p.amount_rupees)}</td>
                  <td className={td}>{p.sms_count.toLocaleString("en-IN")}</td>
                  <td className={td}>
                    <span className={needsAttention(p) ? "font-semibold text-danger" : ""}>
                      {stuckPaid(p) ? "paid, not credited" : p.status.replace(/_/g, " ")}
                    </span>
                    {needsAttention(p) && p.error && <p className="mt-1 max-w-[320px] text-xs text-danger">{p.error}</p>}
                  </td>
                  <td className={`${td} whitespace-nowrap`}>{istDate(p.created_at)}</td>
                  <td className={`${td} whitespace-nowrap`}>{istDate(p.credited_at)}</td>
                  <td className={td}>
                    {(p.status === "credit_failed" || stuckPaid(p)) && (
                      <button type="button" className={btnCls} disabled={busy === `retry-${p.id}`} onClick={() => setRetryId(p.id)}>
                        <Busy on={busy === `retry-${p.id}`}>Retry credit</Busy>
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ConfirmModal
        open={retryId !== null}
        onClose={() => setRetryId(null)}
        title="Retry credit?"
        description="Check this client's balance in Bulk9 first. If the SMS were already added, don't retry."
        confirmLabel="Retry credit"
        tone="warning"
        loading={retryId !== null && busy === `retry-${retryId}`}
        onConfirm={async () => {
          const id = retryId;
          if (!id) return;
          await run(`retry-${id}`, () => retryOperatorSmsCredit(tenantId, id), "Credit retried.");
          setRetryId(null);
        }}
      />
    </div>
  );
}
