"use client";

import { useCallback, useEffect, useState } from "react";
import { KeyRound } from "lucide-react";
import { toast } from "sonner";
import { api, type OtpKey } from "@/lib/api";
import { Btn, Empty, LoadError, Modal, Notice, Skeleton } from "../sms/ui";
import { usePerm } from "../sms/usePerm";
import { CopyButton, SectionCard, StatusPill } from "./otpUi";

const MAX_ACTIVE_KEYS = 2;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

export function OtpKeysCard() {
  const { isOwner, loading } = usePerm();
  const [keys, setKeys] = useState<OtpKey[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<OtpKey | null>(null);
  const [revoking, setRevoking] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.otp.keys();
      setKeys(res.keys);
      setLoadError(null);
    } catch (err) {
      setLoadError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    if (isOwner) void load();
  }, [isOwner, load]);

  async function create() {
    setCreating(true);
    setActionError(null);
    try {
      const res = await api.otp.createKey();
      setNewKey(res.key);
      await load();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setCreating(false);
    }
  }

  async function revoke() {
    if (!revokeTarget) return;
    setRevoking(true);
    setActionError(null);
    try {
      await api.otp.revokeKey(revokeTarget.id);
      toast.success("Key revoked.");
      await load();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setRevoking(false);
      setRevokeTarget(null);
    }
  }

  if (loading) {
    return <Skeleton className="h-40" />;
  }

  const activeCount = keys?.filter((k) => k.status === "active").length ?? 0;
  const canCreate = activeCount < MAX_ACTIVE_KEYS;

  return (
    <>
      <SectionCard
        title="API keys"
        description="For your server to send and check codes through Anril."
        action={
          isOwner ? (
            <Btn variant="outline" busy={creating} disabled={!canCreate || !keys} onClick={() => void create()}>
              Create key
            </Btn>
          ) : undefined
        }
      >
        {!isOwner ? (
          <Notice tone="info">Only the account owner can create OTP API keys.</Notice>
        ) : (
          <div className="space-y-4">
            <Notice tone="warn">Anyone with a key can send codes from your SMS balance and WhatsApp number. Keep it on your server only.</Notice>

            {actionError && <Notice tone="danger">{actionError}</Notice>}

            {!canCreate && (
              <Notice tone="info">
                You already have {MAX_ACTIVE_KEYS} active keys. Revoke one to create another. Two keys let you rotate without downtime.
              </Notice>
            )}

            {newKey && (
              <div className="space-y-3 rounded-xl border border-[#abefc6] bg-[#ecfdf3] p-4">
                <p className="text-sm font-bold text-[#0A1528]">Your new key</p>
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[#e2e8f0] bg-white p-2 pl-3">
                  <code className="min-w-0 flex-1 break-all font-mono text-sm text-[#0A1528]">{newKey}</code>
                  <CopyButton text={newKey} className="shrink-0" />
                </div>
                <Notice tone="warn">Copy it now. Anril won&apos;t show it again.</Notice>
                <div className="flex justify-end">
                  <Btn onClick={() => setNewKey(null)}>Done</Btn>
                </div>
              </div>
            )}

            {loadError ? (
              <LoadError message={loadError} onRetry={() => void load()} />
            ) : !keys ? (
              <Skeleton className="h-24" />
            ) : keys.length === 0 ? (
              <Empty title="No keys yet" hint="Create one, then put it on your server." />
            ) : (
              <ul className="divide-y divide-[#eef2f6]">
                {keys.map((k) => (
                  <li key={k.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                    <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#f1f5f9] text-[#475569]" aria-hidden="true">
                      <KeyRound size={16} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="break-all font-mono text-sm font-bold text-[#0A1528]">{k.key_prefix}…</span>
                        {k.status === "active" ? <StatusPill tone="success">Active</StatusPill> : <StatusPill tone="neutral">Revoked</StatusPill>}
                      </div>
                      <p className="mt-0.5 text-xs text-[#64748b]">
                        Created {formatDate(k.created_at)} · Last used {k.last_used_at ? formatDate(k.last_used_at) : "Never"}
                      </p>
                    </div>
                    {k.status === "active" && (
                      <Btn variant="danger" className="h-8 shrink-0 px-3 text-xs" onClick={() => setRevokeTarget(k)}>
                        Revoke
                      </Btn>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </SectionCard>

      <Modal open={revokeTarget !== null} title="Revoke this key?" onClose={() => setRevokeTarget(null)}>
        <div className="space-y-4">
          <p className="text-sm text-[#334155]">
            Apps using this key will stop working straight away. Key <span className="font-mono font-bold">{revokeTarget?.key_prefix}…</span> cannot be used again.
          </p>
          <div className="flex flex-wrap justify-end gap-2">
            <Btn variant="outline" onClick={() => setRevokeTarget(null)} disabled={revoking}>
              Cancel
            </Btn>
            <Btn variant="danger" busy={revoking} onClick={() => void revoke()}>
              Revoke key
            </Btn>
          </div>
        </div>
      </Modal>
    </>
  );
}
