"use client";
import { useCallback, useEffect, useState } from "react";
import { KeyRound, Plus } from "lucide-react";
import { companionsApi, type CompanionApiKey } from "@/lib/api";
import { ConfirmModal } from "@/components/ConfirmModal";
import { CopyButton } from "@/components/agents/CodeBlock";
import { BTN_PRIMARY, BTN_SECONDARY, CARD, ErrorNote, LoadingRows, formatDate } from "@/components/agents/ui";

/**
 * Secret keys for the business's server. Example: a business creates a key,
 * copies acs_live_… into ANRIL_COMPANION_KEY on their server; the full key
 * is shown once, then only its prefix.
 */
export default function KeysPage() {
  const [keys, setKeys] = useState<CompanionApiKey[] | null>(null);
  const [maxActive, setMaxActive] = useState(2);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<CompanionApiKey | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);

  const load = useCallback(() => {
    setError("");
    companionsApi
      .keys()
      .then((r) => {
        setKeys(r.keys);
        setMaxActive(r.max_active);
      })
      .catch((e: Error) => setError(e.message || "Could not load keys."));
  }, []);
  useEffect(load, [load]);

  const active = (keys ?? []).filter((k) => k.status === "active").length;
  const atLimit = active >= maxActive;

  const create = async () => {
    setCreating(true);
    setError("");
    try {
      const made = await companionsApi.createKey();
      setNewKey(made.key);
      load();
    } catch (e) {
      setError((e as Error).message || "Could not create a key.");
    } finally {
      setCreating(false);
    }
  };

  const revoke = async () => {
    if (!revoking) return;
    setRevokeBusy(true);
    try {
      await companionsApi.revokeKey(revoking.id);
      setRevoking(null);
      load();
    } catch (e) {
      setError((e as Error).message || "Could not revoke the key.");
      setRevoking(null);
    } finally {
      setRevokeBusy(false);
    }
  };

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-secondary">
          {keys ? `${active} of ${maxActive} active keys.` : " "}
          {atLimit && keys ? " Revoke one to make a new one." : ""}
        </p>
        <button type="button" onClick={create} disabled={creating || keys === null || atLimit} className={BTN_PRIMARY} title={atLimit ? `You can have ${maxActive} active keys at once.` : undefined}>
          <Plus size={16} aria-hidden="true" />
          {creating ? "Creating…" : "Create key"}
        </button>
      </div>

      {newKey && (
        <div className="space-y-2 rounded-2xl border border-amber-200 bg-amber-50 p-4" role="status">
          <p className="text-sm font-semibold text-ink">Your new secret key</p>
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 break-all rounded-xl border border-border bg-white p-3 font-mono text-xs text-primary">{newKey}</code>
            <CopyButton text={newKey} />
          </div>
          <p className="text-xs text-amber-800">Copy it now and put it in ANRIL_COMPANION_KEY on your server. You won&apos;t see it again.</p>
          <button type="button" onClick={() => setNewKey(null)} className="text-xs font-medium text-ink-secondary underline underline-offset-2">
            I&apos;ve saved it
          </button>
        </div>
      )}

      {error && <ErrorNote message={error} onRetry={keys === null ? load : undefined} />}

      {keys === null && !error ? (
        <LoadingRows />
      ) : keys && keys.length === 0 ? (
        <div className={`${CARD} py-12 text-center`} role="status">
          <KeyRound className="mx-auto text-ink-muted" size={28} aria-hidden="true" />
          <h2 className="mt-2 text-sm font-semibold text-ink">No keys yet</h2>
          <p className="mt-1 text-sm text-ink-secondary">Create one so your server can sign users in to your characters.</p>
        </div>
      ) : keys ? (
        <div className={`${CARD} overflow-x-auto p-0`}>
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="border-b border-border-subtle text-xs uppercase tracking-wide text-ink-muted">
              <tr>
                <th scope="col" className="px-5 py-3 font-medium">Key</th>
                <th scope="col" className="px-5 py-3 font-medium">Status</th>
                <th scope="col" className="px-5 py-3 font-medium">Created</th>
                <th scope="col" className="px-5 py-3 font-medium">Last used</th>
                <th scope="col" className="px-5 py-3"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id} className="border-b border-border-subtle last:border-0">
                  <td className="px-5 py-3 font-mono text-xs text-ink">{k.key_prefix}…</td>
                  <td className="px-5 py-3">
                    <span className={k.status === "active" ? "text-success" : "text-ink-muted"}>{k.status === "active" ? "Active" : `Revoked ${formatDate(k.revoked_at)}`}</span>
                  </td>
                  <td className="px-5 py-3 text-ink-secondary">{formatDate(k.created_at)}</td>
                  <td className="px-5 py-3 text-ink-secondary">{k.last_used_at ? formatDate(k.last_used_at) : "Never"}</td>
                  <td className="px-5 py-3 text-right">
                    {k.status === "active" && (
                      <button type="button" onClick={() => setRevoking(k)} className={`${BTN_SECONDARY} min-h-8 px-3 text-danger`}>
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <ConfirmModal
        open={revoking !== null}
        onClose={() => setRevoking(null)}
        onConfirm={revoke}
        tone="danger"
        title="Revoke this key?"
        description={`Key ${revoking?.key_prefix ?? ""}… stops working right away. Any site still using it will lose the chat until you put a new key in.`}
        confirmLabel="Revoke key"
        loading={revokeBusy}
        loadingLabel="Revoking…"
      />
    </div>
  );
}
