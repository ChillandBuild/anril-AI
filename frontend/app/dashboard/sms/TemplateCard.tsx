"use client";

import Link from "next/link";
import { Check, Copy, Send } from "lucide-react";
import { toast } from "sonner";
import type { SmsTemplate } from "@/lib/api";
import { cn } from "@/lib/utils";
import { categoryLabel, countVars, formatCount, splitTemplate } from "./helpers";
import { Badge } from "./ui";

/** The SMS as a phone shows it: a grey bubble with each {#var#} as a teal "Variable N" pill. */
export function SmsBubble({ message, className, as: Tag = "p" }: { message: string; className?: string; as?: "p" | "span" }) {
  return (
    <Tag className={cn("block whitespace-pre-wrap break-words rounded-2xl rounded-tl-sm bg-[#f1f5f9] px-3.5 py-2.5 text-sm leading-relaxed text-[#1e293b]", className)}>
      {splitTemplate(message).map((part, i) =>
        part.kind === "text" ? (
          <span key={i}>{part.text}</span>
        ) : (
          <span key={i} className="mx-0.5 rounded bg-[#d9f0f0] px-1.5 py-0.5 text-xs font-bold text-[#036b6e]">
            Variable {part.index + 1}
          </span>
        ),
      )}
    </Tag>
  );
}

/** The round "KE" avatar a phone shows next to the sender. */
export function SenderAvatar({ sender }: { sender: string }) {
  return (
    <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#e6f4f4] text-[11px] font-bold text-[#036b6e]" aria-hidden>
      {sender.slice(0, 2)}
    </span>
  );
}

/** One chip per sender with its template count ("KELIR · 4"). `all` adds an "All" chip first. */
export function SenderChips({
  senders,
  value,
  onChange,
  all,
  label,
}: {
  senders: { sender_id: string; count: number }[];
  value: string;
  onChange: (sender: string) => void;
  all?: number;
  label: string;
}) {
  const chip = (key: string, text: string, count: number) => {
    const on = value === key;
    return (
      <button
        key={key || "__all"}
        type="button"
        aria-pressed={on}
        onClick={() => onChange(key)}
        className={cn(
          "inline-flex h-9 items-center gap-2 rounded-full border px-3.5 text-sm font-bold transition-colors",
          on ? "border-[#038285] bg-[#e6f4f4] text-[#036b6e]" : "border-[#e2e8f0] bg-white text-[#334155] hover:border-[#94a3b8]",
        )}
      >
        {text}
        <span className={cn("rounded-full px-1.5 text-[11px]", on ? "bg-[#b9e3e3] text-[#024f51]" : "bg-[#f1f5f9] text-[#64748b]")}>{formatCount(count)}</span>
      </button>
    );
  };
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {all !== undefined && chip("", "All", all)}
      {senders.map((s) => chip(s.sender_id, s.sender_id, s.count))}
    </div>
  );
}

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${what} copied.`);
  } catch {
    toast.error("Couldn't copy. Select it and copy by hand.");
  }
}

/**
 * One template as the SMS people will get. "full" (Templates tab) adds status, category, the IDs a
 * developer needs (tap to copy) and "Use this template"; "pick" (Send SMS) is the whole card as one button.
 */
export function TemplateCard({
  t,
  variant,
  canSend,
  selected,
  onPick,
}: {
  t: SmsTemplate;
  variant: "full" | "pick";
  canSend?: boolean;
  selected?: boolean;
  onPick?: () => void;
}) {
  const ready = t.status === "ready";
  const vars = Math.max(t.var_count, countVars(t.message));
  const varText = vars === 0 ? "No variables" : `${vars} variable${vars === 1 ? "" : "s"}`;

  if (variant === "pick") {
    return (
      <li>
        <button
          type="button"
          aria-pressed={!!selected}
          onClick={onPick}
          className={cn(
            "flex h-full w-full flex-col gap-2.5 rounded-xl border bg-white p-3.5 text-left transition-colors",
            selected ? "border-[#038285] ring-2 ring-[#038285]" : "border-[#e2e8f0] hover:border-[#94a3b8]",
          )}
        >
          <span className="flex items-center gap-2">
            <SenderAvatar sender={t.sender_id} />
            <span className="text-sm font-bold text-[#0A1528]">{t.sender_id}</span>
            {selected && (
              <span className="ml-auto inline-flex items-center gap-1 text-xs font-bold text-[#036b6e]">
                <Check size={14} /> Selected
              </span>
            )}
          </span>
          <SmsBubble as="span" message={t.message} />
          <span className="flex flex-wrap justify-between gap-x-3 text-xs text-[#64748b]">
            <span>{t.message_id ? `#${t.message_id}` : "No Message ID yet"}</span>
            <span>{varText}</span>
          </span>
        </button>
      </li>
    );
  }

  return (
    <li className="flex flex-col gap-3 rounded-xl border border-[#e2e8f0] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <SenderAvatar sender={t.sender_id} />
        <span className="text-sm font-bold text-[#0A1528]">{t.sender_id}</span>
        <Badge tone={ready ? "success" : "warn"}>{ready ? "Approved" : "Waiting for approval"}</Badge>
        <span className="ml-auto text-xs text-[#64748b]" title="The category DLT approved this template under">
          {categoryLabel(t.template_type)}
        </span>
      </div>
      <SmsBubble message={t.message} />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-[#64748b]">
        {t.message_id && (
          <button type="button" onClick={() => void copy(t.message_id!, "Message ID")} className="inline-flex items-center gap-1 hover:text-[#0A1528]" title="Copy the Message ID (used by the API)">
            Message ID <span className="font-bold text-[#0A1528]">{t.message_id}</span> <Copy size={12} />
          </button>
        )}
        {t.dlt_template_id && (
          <button type="button" onClick={() => void copy(t.dlt_template_id!, "DLT template ID")} className="inline-flex items-center gap-1 hover:text-[#0A1528]" title="Copy the DLT template ID">
            DLT ID <span className="font-bold text-[#0A1528]">{t.dlt_template_id}</span> <Copy size={12} />
          </button>
        )}
        <span>{varText}</span>
        {t.entity_name && <span>{t.entity_name}</span>}
      </div>
      {ready && canSend ? (
        <Link href={`/dashboard/sms/send?template=${encodeURIComponent(t.id)}`} className="inline-flex items-center gap-1.5 self-start text-sm font-bold text-primary hover:underline">
          <Send size={14} /> Use this template
        </Link>
      ) : !ready ? (
        <p className="text-xs text-[#64748b]">It can be used once DLT approves it.</p>
      ) : null}
    </li>
  );
}
