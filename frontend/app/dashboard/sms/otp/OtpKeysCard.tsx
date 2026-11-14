"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import { api, type OtpKey } from "@/lib/api";
import { Badge, Btn, Card, CardHeader, Empty, LoadError, Modal, Notice, Skeleton, TableWrap, tdCls, thCls } from "../ui";
import { usePerm } from "../usePerm";

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

  async function copyNewKey() {
    if (!newKey) return;
    try {
      await navigator.clipboard.writeText(newKey);
      toast.success("Key copied.");
    } catch {
      toast.error("Couldn't copy. Select the key and copy it by hand.");
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
      <Card>
        <CardHeader
          title="OTP API keys"
          hint="For your server to send and check codes through Anril."
          action={
            isOwner ? (
              <Btn variant="outline" busy={creating} disabled={!canCreate || !keys} onClick={() => void create()}>
                Create key
              </Btn>
            ) : undefined
          }
        />
        <div className="space-y-3 p-4 sm:p-5">
          {!isOwner ? (
            <Notice tone="info">Only the account owner can create OTP API keys.</Notice>
          ) : (
            <>
              <Notice tone="warn">Anyone with a key can send codes from your SMS balance and WhatsApp number. Keep it on your server only.</Notice>

              {actionError && <Notice tone="danger">{actionError}</Notice>}

              {!canCreate && (
                <Notice tone="info">
                  You already have {MAX_ACTIVE_KEYS} active keys. Revoke one to create another. Two keys let you rotate without downtime.
                </Notice>
              )}

              {newKey && (
                <div className="space-y-3 rounded-xl border border-[#e2e8f0] p-3 sm:p-4">
                  <Notice tone="warn">Copy it now. Anril won&apos;t show it again.</Notice>
                  <div className="flex flex-wrap items-center gap-2">
                    <code className="min-w-0 flex-1 break-all rounded-xl bg-[#f8fafc] px-3 py-2.5 font-mono text-sm text-[#0A1528]">{newKey}</code>
                    <Btn variant="outline" onClick={() => void copyNewKey()}>
                      <Copy size={14} /> Copy
                    </Btn>
                  </div>
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
                <TableWrap>
                  <table className="min-w-full">
                    <thead className="border-b border-[#e2e8f0] bg-[#f8fafc]">
                      <tr>
                        <th className={thCls}>Key</th>
                        <th className={thCls}>Status</th>
                        <th className={thCls}>Created</th>
                        <th className={thCls}>Last used</th>
                        <th className={thCls}>
                          <span className="sr-only">Actions</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#e2e8f0]">
                      {keys.map((k) => (
                        <tr key={k.id}>
                          <td className={`${tdCls} font-mono`}>{k.key_prefix}…</td>
                          <td className={tdCls}>
                            {k.status === "active" ? <Badge tone="success">Active</Badge> : <Badge tone="neutral">Revoked</Badge>}
                          </td>
                          <td className={tdCls}>{formatDate(k.created_at)}</td>
                          <td className={tdCls}>{k.last_used_at ? formatDate(k.last_used_at) : "Never"}</td>
                          <td className={`${tdCls} text-right`}>
                            {k.status === "active" && (
                              <Btn variant="danger" className="h-8 px-3 text-xs" onClick={() => setRevokeTarget(k)}>
                                Revoke
                              </Btn>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              )}
            </>
          )}
        </div>
      </Card>

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
