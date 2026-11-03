"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { KEY_PLACEHOLDER, buildCurl, buildPython, countVars, friendlyError, maskKey, parseNumbers } from "./helpers";
import { Btn, Card, CardHeader, Field, LoadError, Notice, inputCls } from "./ui";
import { usePerm } from "./usePerm";

type Lang = "curl" | "python";

/** Builds a ready-to-run request for sending an approved template from the client's own software. */
export function ApiBuilderCard() {
  const { isOwner } = usePerm();
  const senders = useSWR("sms:senders", () => api.sms.senders(), { revalidateOnFocus: false });
  const templates = useSWR("sms:templates", () => api.sms.templates(), { revalidateOnFocus: false });
  const [senderId, setSenderId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [numbersText, setNumbersText] = useState("");
  const [vars, setVars] = useState<string[]>([]);
  const [lang, setLang] = useState<Lang>("curl");
  const [maskedKey, setMaskedKey] = useState<string | null>(null);
  const [copying, setCopying] = useState(false);

  const usable = useMemo(
    () => (templates.data?.templates ?? []).filter((t) => t.status === "ready" && !!t.message_id),
    [templates.data],
  );
  const senderList = senders.data?.senders ?? [];
  const forSender = usable.filter((t) => !senderId || t.sender_id === senderId);
  const template = usable.find((t) => t.id === templateId) ?? null;
  const varCount = template ? Math.max(template.var_count ?? 0, countVars(template.message)) : 0;
  const numbers = parseNumbers(numbersText);

  function input(apiKey: string) {
    return {
      senderId: template?.sender_id ?? (senderId || "SENDER"),
      messageId: template?.message_id ?? "TEMPLATE_MESSAGE_ID",
      variables: Array.from({ length: varCount }, (_, i) => vars[i] || `value${i + 1}`),
      numbers: numbers.length > 0 ? numbers : ["9876543210"],
      apiKey,
    };
  }

  function code(apiKey: string): string {
    return lang === "curl" ? buildCurl(input(apiKey)) : buildPython(input(apiKey));
  }

  async function copy() {
    setCopying(true);
    try {
      let apiKey = KEY_PLACEHOLDER;
      if (isOwner) {
        const real = (await api.sms.developerKey()).api_key;
        setMaskedKey(maskKey(real));
        apiKey = real;
      }
      await navigator.clipboard.writeText(code(apiKey));
      toast.success(isOwner ? "Code copied with your API key." : "Code copied. Replace YOUR_API_KEY with the key from your account owner.");
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't copy. Select the code and copy it by hand."));
    } finally {
      setCopying(false);
    }
  }

  const loadFailed = (senders.error && !senders.data) || (templates.error && !templates.data);

  return (
    <Card>
      <CardHeader title="Send from your own app" hint="Pick a sender and an approved template to get code your developer can paste in." />
      <div className="space-y-4 p-4 sm:p-5">
        {loadFailed ? (
          <LoadError message={friendlyError(senders.error ?? templates.error, "Check your connection.")} onRetry={() => { void senders.mutate(); void templates.mutate(); }} />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Sender">
                <select
                  className={inputCls}
                  value={senderId}
                  onChange={(e) => {
                    setSenderId(e.target.value);
                    setTemplateId("");
                    setVars([]);
                  }}
                >
                  <option value="">All senders</option>
                  {senderList.map((s) => (
                    <option key={`${s.entity_id}-${s.sender_id}`} value={s.sender_id}>
                      {s.sender_id}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Approved template">
                <select
                  className={inputCls}
                  value={templateId}
                  onChange={(e) => {
                    setTemplateId(e.target.value);
                    setVars([]);
                  }}
                >
                  <option value="">Choose a template…</option>
                  {forSender.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.message.length > 60 ? `${t.message.slice(0, 60)}…` : t.message}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            {!templates.isLoading && usable.length === 0 && <Notice tone="info">No approved templates are ready yet. Add them in the Templates tab.</Notice>}
            <Field label="Number(s)" hint="10 digits each. Separate several with commas or new lines.">
              <input className={inputCls} inputMode="tel" value={numbersText} onChange={(e) => setNumbersText(e.target.value)} placeholder="9876543210" />
            </Field>
            {varCount > 0 && (
              <div className="grid gap-3 sm:grid-cols-3">
                {Array.from({ length: varCount }, (_, i) => (
                  <Field key={i} label={`Variable ${i + 1}`}>
                    <input
                      className={inputCls}
                      value={vars[i] ?? ""}
                      onChange={(e) =>
                        setVars((v) => {
                          const next = [...v];
                          next[i] = e.target.value;
                          return next;
                        })
                      }
                    />
                  </Field>
                ))}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-2">
              <div role="tablist" aria-label="Code language" className="flex gap-2">
                {(["curl", "python"] as const).map((l) => (
                  <button
                    key={l}
                    type="button"
                    role="tab"
                    aria-selected={lang === l}
                    onClick={() => setLang(l)}
                    className={cn(
                      "h-8 rounded-full border px-3 text-xs font-bold",
                      lang === l ? "border-primary bg-primary/5 text-primary" : "border-[#e2e8f0] text-[#64748b] hover:border-slate-300",
                    )}
                  >
                    {l === "curl" ? "curl" : "Python"}
                  </button>
                ))}
              </div>
              <Btn variant="outline" className="h-8 text-xs" busy={copying} onClick={() => void copy()}>
                <Copy size={13} /> Copy
              </Btn>
            </div>
            <pre className="overflow-x-auto rounded-xl bg-[#0A1528] p-3.5 text-xs leading-relaxed text-[#e2e8f0]">
              <code>{code(isOwner && maskedKey ? maskedKey : KEY_PLACEHOLDER)}</code>
            </pre>
            <p className="text-xs text-[#64748b]">
              {isOwner
                ? "The key is hidden here. Copy fills in your real key. Anyone with the key can send SMS from your balance."
                : "Only the account owner can copy this with the real key. Replace YOUR_API_KEY with it."}
            </p>
          </>
        )}
      </div>
    </Card>
  );
}
