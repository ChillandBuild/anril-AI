"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Check, Copy, Gauge, History, Plug, PlugZap, Sparkles } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { relTime } from "@/lib/operator";
import { ConfirmModal } from "@/components/ConfirmModal";
import {
  capUsage,
  describeClientAction,
  formatAllowedDate,
  parseDailyCap,
  type ClientActionKind,
  type ClientClaudeStatus,
  type ClientConnection,
} from "@/lib/claude-access";
import {
  SaveButton,
  SaveStatus,
  SectionFooter,
  SettingsSection,
  type SaveState,
} from "./SettingsSection";
import { AiraLoader } from "@/components/AiraLoader";

type LoadState = "loading" | "ready" | "error" | "not_owner";
type ApiError = Error & { status?: number };

const FOCUS = "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";
const BUTTON = `rounded-xl border border-border bg-white px-3.5 py-2 font-label text-sm font-semibold text-ink-secondary transition-colors hover:bg-surface-mid disabled:opacity-50 ${FOCUS}`;

const KIND: Record<ClientActionKind, { label: string; className: string }> = {
  ask: { label: "Asked", className: "bg-surface-mid text-ink-secondary" },
  edit: { label: "Changed", className: "bg-sky-50 text-sky-800" },
  send: { label: "Sent", className: "bg-red-50 text-danger" },
  setting: { label: "Setting", className: "bg-surface-mid text-ink-secondary" },
};

async function call<T>(path = "", init: RequestInit = {}): Promise<T> {
  const auth = await getAuthHeaders();
  const res = await fetch(`${API_URL}/api/v1/claude${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...auth },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const error = new Error(typeof body?.detail === "string" ? body.detail : "Request failed") as ApiError;
    error.status = res.status;
    throw error;
  }
  return res.json();
}

/** Remove Claude's saved approval at Supabase, so its old sign-in stops working for good. */
async function clearApprovals(clientIds: string[]): Promise<void> {
  const supabase = createClient();
  for (const clientId of Array.from(new Set(clientIds))) {
    const { error } = await supabase.auth.oauth.revokeGrant({ clientId });
    if (error) throw new Error(error.message);
  }
}

function when(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const time = date.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  if (date.toDateString() === new Date().toDateString()) return time;
  return `${date.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}, ${time}`;
}

function CopyField({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-2">
      <code className="min-w-0 flex-1 truncate rounded-xl border border-border bg-surface-subtle px-3 py-2 font-mono text-xs text-ink">
        {value}
      </code>
      <button type="button" onClick={copy} aria-label={`Copy ${label}`} className={`inline-flex items-center gap-1.5 ${BUTTON}`}>
        {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
        <span aria-live="polite">{copied ? "Copied" : "Copy"}</span>
      </button>
    </div>
  );
}

export function ClaudeConnectorPanel() {
  const [data, setData] = useState<ClientClaudeStatus | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "ok" | "warn"; text: string } | null>(null);
  const [capInput, setCapInput] = useState("");
  const [capState, setCapState] = useState<SaveState>("idle");
  const [capError, setCapError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const status = await call<ClientClaudeStatus>();
      setData(status);
      setCapInput(String(status.daily_cap));
      setLoadState("ready");
    } catch (e) {
      setLoadState((e as ApiError).status === 403 ? "not_owner" : "error");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loadState === "loading") return <AiraLoader inline className="min-h-[200px]" />;
  if (loadState === "not_owner") {
    return (
      <Plain title="Only the account owner can use this">
        Anril AI for Claude can read leads and message customers, so only the owner of the account can connect it.
      </Plain>
    );
  }
  if (loadState === "error" || !data) {
    return (
      <div className="flex min-h-[200px] flex-col items-center justify-center gap-3 text-center">
        <p className="font-body text-sm text-ink-muted">Couldn&apos;t load this page.</p>
        <button type="button" onClick={() => { setLoadState("loading"); load(); }} className="btn-primary px-5 py-2 text-sm">
          Retry
        </button>
      </div>
    );
  }
  if (!data.available || !data.oauth_client_id) {
    return (
      <Plain title="Not switched on for your account">
        Ask your Anril account manager to switch on Anril AI. Nothing else is needed from you.
      </Plain>
    );
  }

  const active = data.connections.filter((c) => c.status === "active");
  const connected = active.length > 0;
  const everConnected = data.connections.length > 0;
  const appIds = [...data.connections.map((c) => c.client_id), data.oauth_client_id];

  async function disconnect() {
    setBusy(true);
    setNotice(null);
    try {
      const res = await call<{ revoked: number; connections: ClientConnection[] }>("/revoke", { method: "POST" });
      setData((prev) => (prev ? { ...prev, connections: res.connections } : prev));
      setConfirmOpen(false);
      try {
        // Our switch is off, so Claude is already stopped. Also remove the saved approval, or an
        // old sign-in would work again the next time this app is allowed.
        await clearApprovals(appIds);
        setNotice({ tone: "ok", text: "Disconnected. Claude can no longer use your account." });
      } catch {
        setNotice({
          tone: "warn",
          text: "Disconnected: Claude is stopped. Anril could not also clear the old approval, so press Clear old approval before you connect again.",
        });
      }
    } catch (e) {
      setConfirmOpen(false);
      setNotice({ tone: "warn", text: e instanceof Error && e.message ? e.message : "Could not disconnect. Try again." });
    } finally {
      setBusy(false);
    }
  }

  async function clearOldApproval() {
    setBusy(true);
    setNotice(null);
    try {
      await clearApprovals(appIds);
      setNotice({ tone: "ok", text: "Old approval cleared. Connect again from the Claude app to see the Allow screen." });
    } catch (e) {
      setNotice({ tone: "warn", text: e instanceof Error && e.message ? e.message : "Could not clear the old approval." });
    } finally {
      setBusy(false);
    }
  }

  const max = data.max_daily_cap;
  const typedCap = parseDailyCap(capInput, max);
  const capDirty = typedCap !== null && typedCap !== data.daily_cap;
  const usage = capUsage(data.sent_today, data.daily_cap);

  async function saveCap() {
    if (typedCap === null || !capDirty) return;
    setCapState("saving");
    setCapError(null);
    try {
      const res = await call<{ daily_cap: number }>("/cap", { method: "PUT", body: JSON.stringify({ daily_cap: typedCap }) });
      setData((prev) => (prev ? { ...prev, daily_cap: res.daily_cap } : prev));
      setCapInput(String(res.daily_cap));
      setCapState("saved");
      setTimeout(() => setCapState("idle"), 2000);
    } catch (e) {
      setCapState("idle");
      setCapError(e instanceof Error && e.message ? e.message : "Could not save the limit.");
    }
  }

  return (
    <div className="space-y-4">
      {notice && (
        <div
          role={notice.tone === "warn" ? "alert" : "status"}
          className={`rounded-xl border px-3.5 py-2.5 font-body text-sm ${
            notice.tone === "warn" ? "border-amber-200 bg-amber-50 text-amber-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"
          }`}
        >
          {notice.text}
        </div>
      )}

      <SettingsSection
        id="claude-connect"
        icon={Plug}
        accent="violet"
        title="Connect your Claude app"
        description="Add Anril AI to Claude once. Owner only."
        status={{ label: connected ? "Connected" : "Not connected", tone: connected ? "on" : "off" }}
      >
        <ol className="list-decimal space-y-3 pl-5 font-body text-sm text-ink-secondary">
          <li>
            In Claude, open <b className="text-ink">Settings → Connectors → Add custom connector</b>.
          </li>
          <li>
            Paste this address:
            <CopyField value={data.mcp_url} label="the connector address" />
          </li>
          <li>
            Open <b className="text-ink">Advanced settings</b> and paste this as the OAuth Client ID:
            <CopyField value={data.oauth_client_id} label="the OAuth Client ID" />
          </li>
          <li>
            Press <b className="text-ink">Connect</b>, then <b className="text-ink">Allow</b> on the Anril page that opens.
          </li>
        </ol>
        {!connected && everConnected && (
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border-subtle pt-4">
            <button type="button" onClick={clearOldApproval} disabled={busy} className={BUTTON}>
              Clear old approval
            </button>
            <span className="font-body text-xs text-ink-muted">
              Use this if Claude says it is already approved and never shows the Allow screen.
            </span>
          </div>
        )}
      </SettingsSection>

      {connected && (
        <>
          <SettingsSection
            id="claude-connected"
            icon={PlugZap}
            accent="emerald"
            title="Connected"
            description="The Claude app that can use your account right now."
            status={{ label: "On", tone: "on" }}
          >
            <ul className="space-y-1 font-body text-sm text-ink-secondary">
              {active.map((c) => (
                <li key={c.id}>
                  {c.label || "Claude app"} · allowed on {formatAllowedDate(c.created_at)} ·{" "}
                  {c.last_used_at ? `last used ${relTime(c.last_used_at)}` : "not used yet"}
                </li>
              ))}
            </ul>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => setConfirmOpen(true)}
                disabled={busy}
                className={`rounded-xl border border-red-200 bg-white px-3.5 py-2 font-label text-sm font-semibold text-danger transition-colors hover:bg-red-50 disabled:opacity-50 ${FOCUS}`}
              >
                Disconnect
              </button>
              <span className="font-body text-xs text-ink-muted">Stops Claude at once. You can connect again any time.</span>
            </div>
          </SettingsSection>

          <SettingsSection
            id="claude-cap"
            icon={Gauge}
            accent="amber"
            title="Daily sending limit"
            description="The most customer messages Claude may send for you in one day (replies and broadcasts together)."
            dirty={capDirty}
          >
            <label htmlFor="claude-daily-cap" className="font-label text-sm font-semibold text-ink">
              Messages a day
            </label>
            <div className="mt-1.5 flex flex-wrap items-center gap-3">
              <input
                id="claude-daily-cap"
                type="text"
                inputMode="numeric"
                value={capInput}
                onChange={(e) => { setCapInput(e.target.value); setCapError(null); }}
                aria-invalid={typedCap === null}
                aria-describedby="claude-daily-cap-hint"
                className={`w-28 rounded-xl border bg-white px-3 py-2 font-body text-sm text-ink ${FOCUS} ${
                  typedCap === null ? "border-red-300" : "border-border"
                }`}
              />
              <span id="claude-daily-cap-hint" className={`font-body text-xs ${typedCap === null ? "text-danger" : "text-ink-muted"}`}>
                {typedCap === null
                  ? `Enter a whole number from 0 to ${max.toLocaleString("en-IN")}.`
                  : "Set 0 to stop all sending."}
              </span>
            </div>
            <div
              className="mt-4 h-2 overflow-hidden rounded-full bg-surface-mid"
              role="progressbar"
              aria-label="Used today"
              aria-valuemin={0}
              aria-valuemax={data.daily_cap}
              aria-valuenow={Math.min(data.sent_today, data.daily_cap)}
            >
              <div className="h-full bg-primary" style={{ width: `${usage.percent}%` }} />
            </div>
            <p className="mt-1.5 font-body text-xs text-ink-muted">
              <b className="text-ink">{data.sent_today.toLocaleString("en-IN")}</b> of{" "}
              <b className="text-ink">{data.daily_cap.toLocaleString("en-IN")}</b> used today · {usage.left.toLocaleString("en-IN")} left ·
              resets at midnight, Indian time
            </p>
            {capError && (
              <p role="alert" className="mt-2 font-body text-xs text-danger">
                {capError}
              </p>
            )}
            <SectionFooter status={<SaveStatus state={capState} dirty={capDirty} />}>
              <SaveButton state={capState} dirty={capDirty} disabled={typedCap === null} onClick={saveCap} />
            </SectionFooter>
          </SettingsSection>

          <SettingsSection
            id="claude-recent"
            icon={History}
            accent="sky"
            title="What Claude did recently"
            description="The last few things done through Anril AI."
          >
            {data.recent.length === 0 ? (
              <p className="font-body text-sm text-ink-muted">Nothing yet. Ask Claude something about your business.</p>
            ) : (
              <ul className="divide-y divide-border-subtle">
                {data.recent.map((row) => {
                  const action = describeClientAction(row);
                  return (
                    <li key={row.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2 font-body text-sm">
                      <span className="w-28 shrink-0 text-xs text-ink-muted">{when(row.created_at)}</span>
                      <span className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold ${KIND[action.kind].className}`}>
                        {KIND[action.kind].label}
                      </span>
                      <span className="min-w-0 flex-1 break-words text-ink-secondary">{action.text}</span>
                    </li>
                  );
                })}
              </ul>
            )}
            <p className="mt-3 font-body text-xs text-ink-muted">
              Full history:{" "}
              <Link href="/dashboard/roles?tab=audit" className={`text-primary hover:underline ${FOCUS}`}>
                Roles → Audit log
              </Link>
            </p>
          </SettingsSection>
        </>
      )}

      <ConfirmModal
        open={confirmOpen}
        onClose={() => { if (!busy) setConfirmOpen(false); }}
        onConfirm={disconnect}
        title="Disconnect Claude"
        description="Claude stops working with your Anril account at once. A broadcast it already scheduled still goes out unless you cancel it in Broadcasts."
        tone="danger"
        confirmLabel="Disconnect"
        loading={busy}
        loadingLabel="Disconnecting…"
      />
    </div>
  );
}

function Plain({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-border bg-white p-5">
      <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
        <Sparkles size={16} className="text-primary" aria-hidden="true" />
        {title}
      </h2>
      <p className="mt-1.5 font-body text-sm text-ink-secondary">{children}</p>
    </div>
  );
}
