"use client";

import { useState } from "react";
import { Copy, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { friendlyError } from "./helpers";
import { Btn, Card, CardHeader, Notice } from "./ui";
import { usePerm } from "./usePerm";

export function ApiKeyCard() {
  const { isOwner } = usePerm();
  const [key, setKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reveal() {
    setBusy(true);
    setError(null);
    try {
      setKey((await api.sms.developerKey()).api_key);
    } catch (err) {
      setError(friendlyError(err, "Couldn't load the key"));
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!key) return;
    try {
      await navigator.clipboard.writeText(key);
      toast.success("Key copied.");
    } catch {
      toast.error("Couldn't copy. Select the key and copy it by hand.");
    }
  }

  return (
    <Card>
      <CardHeader title="API key" hint="For developers who want to send SMS from their own software." />
      <div className="space-y-3 p-4 sm:p-5">
        {!isOwner ? (
          <Notice tone="info">Only the account owner can see the API key.</Notice>
        ) : (
          <>
            <Notice tone="warn">Anyone with this key can send SMS from your balance.</Notice>
            {error && <Notice tone="danger">{error}</Notice>}
            {key ? (
              <div className="flex flex-wrap items-center gap-2">
                <code className="min-w-0 flex-1 break-all rounded-xl bg-[#f8fafc] px-3 py-2.5 text-sm text-[#0A1528]">{key}</code>
                <Btn variant="outline" onClick={() => void copy()}>
                  <Copy size={14} /> Copy
                </Btn>
                <Btn variant="outline" onClick={() => setKey(null)}>
                  <EyeOff size={14} /> Hide
                </Btn>
              </div>
            ) : (
              <Btn variant="outline" busy={busy} onClick={() => void reveal()}>
                <Eye size={14} /> Show API key
              </Btn>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
