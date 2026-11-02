"use client";
import { toast } from "sonner";
import { Fragment, memo, useCallback, useEffect, useRef, useState } from "react";
import { api, Lead, Message } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { cn, formatPhone } from "@/lib/utils";
import { usePolling } from "@/hooks/usePolling";
import { useScheduledTemplates } from "@/hooks/useScheduledTemplates";
import { ScheduledBubbles } from "@/components/schedule/scheduled-messages";
import { ChannelAvatar, getChannel, CHANNEL_LABEL } from "./channel-avatar";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { SwitchPill } from "@/components/ui/controls";
import { useMasterAiEnabled } from "@/lib/useMasterAiEnabled";
import { ShareProductMenu } from "@/components/chat/ShareProductMenu";
import { NewDealDialog } from "@/components/deals/NewDealDialog";
import { fetchHandovers, resolveHandover } from "@/lib/escalations";
import {
  CheckCircle2,
  AlertTriangle, Pencil, Trash2,
  FileText, Image as ImageIcon,
  Music, Video, Download, X, Eraser, MoreVertical,
  ArrowLeft, Check, CheckCheck, Flag, Info, Smile, SendHorizontal, Paperclip, CreditCard, Lock,
} from "lucide-react";
import { SendTemplateModal } from "@/app/dashboard/leads/SendTemplateModal";

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function formatDateDivider(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  if (isSameDay(date, now)) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (isSameDay(date, yesterday)) return "Yesterday";
  return date.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "long",
    year: date.getFullYear() === now.getFullYear() ? undefined : "numeric",
  });
}

// ─── Media bubble renderer ────────────────────────────────────────────────────
function MediaBubble({ msg }: { msg: Message }) {
  const mediaType = msg.media_type;
  const filename = msg.media_filename || "file";
  const isOutbound = msg.direction === "outbound";

  if (!mediaType) return null;

  if (mediaType === "image") {
    // Images: show placeholder since we store meta:ID not public URL
    return (
      <div className={cn(
        "max-w-[240px] rounded-xl overflow-hidden border",
        isOutbound ? "border-white/20" : "border-surface-mid"
      )}>
        <div className={cn(
          "flex flex-col items-center justify-center gap-2 p-6 rounded-xl",
          isOutbound ? "bg-white/10" : "bg-surface-low"
        )}>
          <ImageIcon size={32} className={isOutbound ? "text-white/70" : "text-on-surface-muted"} />
          <span className={cn("font-label text-xs truncate max-w-[180px]", isOutbound ? "text-white/80" : "text-on-surface-muted")}>
            {filename}
          </span>
        </div>
      </div>
    );
  }

  if (mediaType === "audio") {
    return (
      <div className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-xl",
        isOutbound ? "bg-white/10" : "bg-surface-low"
      )}>
        <Music size={16} className={isOutbound ? "text-white/80" : "text-secondary"} />
        <span className={cn("font-label text-xs", isOutbound ? "text-white/80" : "text-on-surface-muted")}>
          {filename}
        </span>
      </div>
    );
  }

  if (mediaType === "video") {
    return (
      <div className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-xl",
        isOutbound ? "bg-white/10" : "bg-surface-low"
      )}>
        <Video size={16} className={isOutbound ? "text-white/80" : "text-secondary"} />
        <span className={cn("font-label text-xs", isOutbound ? "text-white/80" : "text-on-surface-muted")}>
          {filename}
        </span>
      </div>
    );
  }

  // Document / sticker / default
  return (
    <div className={cn(
      "flex items-center gap-2 px-3 py-2 rounded-xl border",
      isOutbound ? "bg-white/10 border-white/20" : "bg-surface-low border-surface-mid"
    )}>
      <FileText size={16} className={isOutbound ? "text-white/80" : "text-secondary"} />
      <div className="min-w-0">
        <p className={cn("font-label text-xs font-semibold truncate max-w-[160px]", isOutbound ? "text-white" : "text-on-surface")}>
          {filename}
        </p>
        <p className={cn("font-label text-[10px]", isOutbound ? "text-white/60" : "text-on-surface-muted")}>
          {mediaType}
        </p>
      </div>
      <Download size={13} className={isOutbound ? "text-white/60" : "text-on-surface-muted"} />
    </div>
  );
}

// ─── Single message bubble (memoized — only re-renders when this message changes) ─
const MessageBubble = memo(function MessageBubble({ msg }: { msg: Message }) {
  const isOutbound = msg.direction === "outbound";
  const isAi = isOutbound && msg.is_ai_generated;
  // Where an AI reply came from, shown in its label.
  const aiSource = !isAi ? null
    : msg.media_type === "image" ? "media recommendation"
    : msg.reply_source === "knowledge" ? "📄 Knowledge Base"
    : null;

  return (
    <div className={cn("flex", isOutbound && "justify-end")}>
      <div className={cn(
        "max-w-[82%] md:max-w-[62%] px-3.5 py-2 rounded-2xl font-body text-[12.5px] leading-relaxed",
        isOutbound
          ? isAi
            ? "bg-[#e6f6f5] text-[#0A1528] border border-primary/10 rounded-tr-md"
            : "bg-primary text-white rounded-tr-md"
          : "bg-white border border-[#eef1f5] text-[#0A1528] rounded-tl-md shadow-sm"
      )}>
        {isAi && (
          <p className="mb-0.5 text-[10.5px] font-bold text-primary">
            ✦ Anril AI{aiSource && <span className="font-semibold text-[#64748b]"> · {aiSource}</span>}
          </p>
        )}
        {msg.media_type && <MediaBubble msg={msg} />}
        {msg.content && !(msg.media_type && msg.content.startsWith("[")) && (
          <p className={cn("whitespace-pre-wrap", msg.media_type && "mt-1.5 text-xs opacity-80")}>
            {msg.content}
          </p>
        )}
        <p className={cn(
          "mt-1 flex items-center gap-1 text-[10px]",
          isOutbound && !isAi ? "text-white/70" : "text-[#64748b]"
        )}>
          {isOutbound && !isAi && <span>Sent by you ·</span>}
          <span>{new Date(msg.created_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}</span>
          {isOutbound && <CheckCheck size={12} />}
        </p>
      </div>
    </div>
  );
});

// ─── Date divider (WhatsApp-style day separator) ──────────────────────────────
function DateDivider({ dateStr }: { dateStr: string }) {
  return (
    <div className="flex justify-center my-3 select-none">
      <span className="rounded-full bg-slate-50 px-3 py-1 font-label text-[11px] font-semibold text-[#64748b] shadow-sm">
        {formatDateDivider(dateStr)}
      </span>
    </div>
  );
}

// ─── Selected file preview ────────────────────────────────────────────────────
function FilePreview({ file, onRemove }: { file: File; onRemove: () => void }) {
  const isImage = file.type.startsWith("image/");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    if (isImage) {
      const url = URL.createObjectURL(file);
      setPreviewUrl(url);
      return () => URL.revokeObjectURL(url);
    }
  }, [file, isImage]);

  const sizeMB = (file.size / 1024 / 1024).toFixed(1);

  return (
    <div className="flex items-center gap-2 px-3 py-2 mb-2 bg-slate-50 rounded-xl border border-[#e2e8f0]">
      {isImage && previewUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={previewUrl} alt={file.name} loading="lazy" decoding="async" className="w-10 h-10 object-cover rounded-lg shrink-0" />
      ) : (
        <div className="w-10 h-10 bg-primary/10 rounded-lg flex items-center justify-center shrink-0">
          <FileText size={18} className="text-primary" />
        </div>
      )}
      <div className="flex-1 min-w-0">
        <p className="font-label text-xs font-semibold text-[#0A1528] truncate">{file.name}</p>
        <p className="font-label text-[10px] text-[#64748b]">{sizeMB} MB</p>
      </div>
      <button onClick={onRemove} className="p-1 rounded-lg hover:bg-slate-200 transition-colors text-[#64748b] hover:text-red-500">
        <X size={14} />
      </button>
    </div>
  );
}

// ─── Main ChatThread component ────────────────────────────────────────────────
export function ChatThread({
  lead,
  onDeleted,
  onLeadUpdate,
  onBack,
  detailsOpen = false,
  onToggleDetails,
}: {
  lead: Lead;
  onDeleted?: (id: string) => void;
  onLeadUpdate?: (updated: Lead) => void;
  onBack?: () => void;
  detailsOpen?: boolean;
  onToggleDetails?: () => void;
}) {
  const { role, permissions } = useAuthRole();
  const masterAiEnabled = useMasterAiEnabled();
  const canReplyToConversations = role === "owner" || permissions.includes("conversations.reply");
  const canManageDeals = role === "owner" || permissions.includes("deals.manage");
  const [paymentDealOpen, setPaymentDealOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [current, setCurrent] = useState<Lead>(lead);
  const [converting, setConverting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // Media state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileCaption, setFileCaption] = useState("");

  // New header state
  const [callers, setCallers] = useState<Record<string, string>>({});
  const [handovers, setHandovers] = useState<Array<{ id: string; lead_id: string; reason?: string | null }>>([]);
  const [templateModalOpen, setTemplateModalOpen] = useState(false);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [resolvingHandover, setResolvingHandover] = useState(false);

  // Templates waiting to go out show in the thread as dashed bubbles.
  const scheduled = useScheduledTemplates(lead.id, { enabled: canReplyToConversations });
  const reloadScheduled = scheduled.refresh;
  const refreshScheduled = useRef(reloadScheduled);
  useEffect(() => {
    refreshScheduled.current = reloadScheduled;
  });
  const scheduledKey = scheduled.items.map((s) => `${s.id}:${s.status}:${s.send_at}`).join("|");

  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const emojiRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setCurrent(lead);
    setDraft("");
    setSendError(null);
    setEditingName(false);
    setSelectedFile(null);
    setFileCaption("");
  }, [lead.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync fields that the right panel may update externally
  useEffect(() => {
    setCurrent((prev) => ({
      ...prev,
      ai_enabled: lead.ai_enabled,
      converted_at: lead.converted_at,
      name: lead.name,
      score: lead.score,
      segment: lead.segment,
    }));
  }, [lead.ai_enabled, lead.converted_at, lead.name, lead.score, lead.segment]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
      if (emojiRef.current && !emojiRef.current.contains(e.target as Node)) {
        setEmojiOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Load callers and handovers on mount
  useEffect(() => {
    (async () => {
      try {
        const res = await api.callers.list();
        const callerMap: Record<string, string> = {};
        (res.data || []).forEach((c: { id: string; name: string }) => {
          callerMap[c.id] = c.name;
        });
        setCallers(callerMap);
      } catch {
        // Silent fail
      }

      try {
        const ho = await fetchHandovers();
        setHandovers(ho);
      } catch {
        // Silent fail
      }
    })();
    // Re-read on each lead so the escalation reason belongs to the chat on screen.
  }, [lead.id]);

  async function saveName() {
    const trimmed = nameDraft.trim();
    setEditingName(false);
    if (!trimmed || trimmed === current.name) return;
    try {
      const updated = await api.leads.update(lead.id, { name: trimmed });
      setCurrent(updated);
      onLeadUpdate?.(updated);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Rename failed");
    }
  }

  async function markConverted() {
    if (!confirm(`Mark ${lead.name || lead.phone} as converted? This feeds AI Auto-Tune.`)) return;
    setConverting(true);
    try {
      const updated = await api.leads.convert(lead.id);
      setCurrent(updated);
      onLeadUpdate?.(updated);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally { setConverting(false); }
  }

  async function deleteConversation() {
    if (!confirm(`Delete the conversation with ${current.name || current.phone}? This removes the lead from every page. This action cannot be undone from the dashboard.`)) return;
    setDeleting(true);
    try {
      await api.leads.delete(lead.id);
      onDeleted?.(lead.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
      setDeleting(false);
    }
  }

  async function clearData() {
    if (!confirm(`Erase everything about ${current.name || current.phone}: messages, bookings, payments, notes and score? Any unpaid payment link is cancelled. This cannot be undone. Their next message starts as a brand-new lead.`)) return;
    setClearing(true);
    try {
      await api.leads.clearData(lead.id);
      onDeleted?.(lead.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Clear failed");
      setClearing(false);
    }
  }

  async function toggleAI() {
    try {
      const updated = await api.leads.toggleAI(lead.id, !current.ai_enabled);
      setCurrent(updated);
      onLeadUpdate?.(updated);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Toggle failed");
    }
  }

  function closeTemplateModal() {
    setTemplateModalOpen(false);
    // Show the template that was just sent.
    void pollMessages();
  }

  async function markResolved() {
    setResolvingHandover(true);
    try {
      // Fetch fresh: an escalation may have opened after this chat was loaded.
      const pending = (await fetchHandovers()).filter((h) => h.lead_id === current.id);
      if (pending.length === 0) {
        toast.info("Nothing to resolve");
        setResolvingHandover(false);
        return;
      }
      for (const h of pending) {
        await resolveHandover(h.id);
      }
      // Refetch the lead
      const fresh = await api.leads.get(current.id);
      setCurrent(fresh);
      onLeadUpdate?.(fresh);
      toast.success("Marked resolved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to resolve");
    } finally { setResolvingHandover(false); }
  }

  function getSegmentPill() {
    const segmentInfo: Record<string, { icon: string; label: string; bg: string; text: string; border: string }> = {
      A: { icon: "🔥", label: "Hot lead", bg: "bg-orange-50", text: "text-orange-600", border: "border-orange-200" },
      B: { icon: "🌡️", label: "Warm lead", bg: "bg-amber-50", text: "text-amber-600", border: "border-amber-200" },
      C: { icon: "❄️", label: "Cold lead", bg: "bg-blue-50", text: "text-blue-600", border: "border-blue-200" },
      D: { icon: "👋", label: "Not interested", bg: "bg-slate-50", text: "text-slate-600", border: "border-slate-200" },
    };
    const info = segmentInfo[current.segment] || segmentInfo.D;
    return info;
  }

  async function sendReply() {
    const text = draft.trim();
    if (!canReplyToConversations || replyLocked || !text || sending) return;
    setSending(true);
    setSendError(null);
    try {
      const sentMsg = await api.leads.sendMessage(lead.id, text);
      setMessages((prev) => {
        const msgId = sentMsg.id || (sentMsg as unknown as Record<string, unknown>).sid || Date.now().toString();
        if (prev.some((m) => m.id === msgId)) return prev;
        return [...prev, sentMsg as Message];
      });
      setDraft("");
    } catch (err) {
      setSendError(err instanceof Error ? err.message : "Send failed");
    } finally { setSending(false); }
  }

  async function sendMedia() {
    if (!canReplyToConversations || !selectedFile || sending) return;
    setSending(true);
    setSendError(null);
    try {
      const sentMsg = await api.leads.sendMedia(lead.id, selectedFile, fileCaption || undefined);
      setMessages((prev) => {
        if (prev.some((m) => m.id === sentMsg.id)) return prev;
        return [...prev, sentMsg as Message];
      });
      setSelectedFile(null);
      setFileCaption("");
    } catch (err) {
      setSendError(err instanceof Error ? err.message : "Media send failed");
    } finally { setSending(false); }
  }


  useEffect(() => {
    let mounted = true;
    setLoading(true);

    const fetchMsgs = async () => {
      try {
        const msgs = await api.leads.messages(lead.id);
        if (mounted) { setMessages(msgs); setLoading(false); }
      } catch {
        if (mounted) setLoading(false);
      }
    };

    fetchMsgs();

    const channel = supabase
      .channel(`messages:${lead.id}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "messages", filter: `lead_id=eq.${lead.id}` },
        (payload) => {
          if (!mounted) return;
          setMessages((prev) => {
            if (prev.some((m) => m.id === payload.new.id)) return prev;
            return [...prev, payload.new as Message];
          });
          // A scheduled template that just went out is now a real message, so its dashed bubble must go.
          if (payload.new.direction === "outbound") void refreshScheduled.current();
        }
      )
      .subscribe();

    return () => {
      mounted = false;
      supabase.removeChannel(channel);
    };
  }, [lead.id]);

  const pollMessages = useCallback(() => {
    api.leads.messages(lead.id).then((newMsgs) => {
      setMessages((prev) => {
        if (
          prev.length !== newMsgs.length ||
          (prev.length > 0 && newMsgs.length > 0 && prev[prev.length - 1].id !== newMsgs[newMsgs.length - 1].id)
        ) return newMsgs;
        return prev;
      });
    }).catch(() => { /* silent — realtime is primary */ });
    void reloadScheduled();
  }, [lead.id, reloadScheduled]);

  usePolling(pollMessages, 15000);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, scheduledKey]);

  const aiEnabled = current.ai_enabled !== false;
  const converted = Boolean(current.converted_at);
  const isInstagram = current.source === "instagram";
  const isTelegram = current.source === "telegram";
  const isFacebook = current.source === "facebook";
  const isWhatsApp = !isInstagram && !isTelegram && !isFacebook;
  const canSendMedia = canReplyToConversations && (!aiEnabled || !masterAiEnabled) && isWhatsApp;

  const lastInbound = [...messages].reverse().find((m) => m.direction === "inbound");
  const hoursSinceInbound = lastInbound
    ? (Date.now() - new Date(lastInbound.created_at).getTime()) / 3_600_000
    : Infinity;
  const outsideWindow = hoursSinceInbound > 24;
  // WhatsApp drops free-text replies after 24h, so the reply box is blurred and only templates go out.
  // Wait for messages to load, or every thread would flash locked before its last inbound arrives.
  const replyLocked = !loading && outsideWindow && isWhatsApp && canReplyToConversations;

  const segmentPill = getSegmentPill();
  const hasEscalation = current.needs_human_attention || current.needs_human_intervention;
  const pendingHandover = handovers.find((h) => h.lead_id === current.id);

  return (
    <div className="flex-1 flex flex-col h-full min-w-0">
      {/* Header */}
      <div className="px-5 py-3 border-b border-[#e2e8f0] bg-white flex items-center gap-3">
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-[#0A1528] hover:bg-slate-200 md:hidden"
            title="Back to conversations"
          >
            <ArrowLeft size={18} />
          </button>
        )}

        {/* Lead initials avatar */}
        <ChannelAvatar source={current.source} size={38} />

        {/* Name + segment pill + subtitle */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            {editingName ? (
              <input
                autoFocus
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onBlur={saveName}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveName();
                  if (e.key === "Escape") setEditingName(false);
                }}
                placeholder="Add a name"
                className="font-display text-[15px] font-bold text-[#0A1528] bg-slate-50 px-2 py-0.5 rounded border border-primary focus:outline-none focus:ring-1 focus:ring-primary flex-1"
              />
            ) : (
              <button
                onClick={() => { setNameDraft(current.name || ""); setEditingName(true); }}
                className="group flex items-center gap-1.5"
                title="Click to rename"
              >
                <span className="font-display text-[15px] font-bold text-[#0A1528] truncate">
                  {current.name || current.phone || "Unknown"}
                </span>
                <Pencil size={13} className="opacity-0 group-hover:opacity-50 text-[#94a3b8] shrink-0" />
              </button>
            )}
            <div className={cn(
              "rounded-full px-2 py-0.5 text-[10.5px] font-bold border",
              segmentPill.bg,
              segmentPill.text,
              segmentPill.border
            )}>
              {segmentPill.icon} {segmentPill.label}
            </div>
          </div>
          <p className="font-label text-[11px] text-[#64748b] flex items-center gap-1 flex-wrap">
            {formatPhone(current.phone) || "—"}
            <span className="text-[#cbd5e1]">·</span>
            {CHANNEL_LABEL[getChannel(current.source)]}
            {current.ad_campaign_id || current.ad_campaign_name ? (
              <>
                <span className="text-[#cbd5e1]">·</span>
                <span>From Meta Ad{current.ad_campaign_name ? ` (${current.ad_campaign_name})` : ""}</span>
              </>
            ) : null}
            {current.assigned_to ? (
              <>
                <span className="text-[#cbd5e1]">·</span>
                <span>Assigned to {callers[current.assigned_to] || "a teammate"}</span>
              </>
            ) : null}
          </p>
        </div>

        {/* Right side controls */}
        <div className="ml-auto flex items-center gap-2">
          {/* AI replies switch */}
          <div
            className={`rounded-xl border border-[#e2e8f0] px-3 py-1.5 flex items-center gap-2${masterAiEnabled ? "" : " opacity-50"}`}
            title={masterAiEnabled ? undefined : "AI is off for your whole account — turn it on in Settings → Auto-Reply"}
          >
            <span className="text-[12px] font-semibold text-[#0A1528]">AI replies</span>
            <SwitchPill on={masterAiEnabled && aiEnabled} disabled={!masterAiEnabled} onChange={() => toggleAI()} size="sm" aria-label="AI replies" />
            <span className="text-[11px] text-[#64748b]">{!masterAiEnabled ? "Off (account)" : aiEnabled ? "On" : "Off"}</span>
          </div>

          {/* Mark resolved button - only show if escalated */}
          {hasEscalation && (
            <button
              onClick={markResolved}
              disabled={resolvingHandover}
              className="rounded-xl bg-primary px-3.5 py-2 text-[12px] font-bold text-white hover:bg-[var(--primary-900)] disabled:opacity-50 flex items-center gap-1.5"
              title="Mark this escalation as resolved"
            >
              <Check size={14} />
              {resolvingHandover ? "Resolving…" : "Mark resolved"}
            </button>
          )}

          {/* Lead info button - only at xl and up */}
          {onToggleDetails && (
            <button
              onClick={onToggleDetails}
              className="hidden xl:flex rounded-xl border border-[#e2e8f0] px-3 py-2 text-[12px] font-semibold text-primary items-center gap-1 hover:bg-slate-50"
              title={detailsOpen ? "Hide lead info" : "Show lead info"}
            >
              <Info size={13} />
              {detailsOpen ? "Hide info" : "Lead info ›"}
            </button>
          )}

          {/* More menu */}
          <div className="relative shrink-0" ref={dropdownRef}>
            <button
              onClick={() => setDropdownOpen((v) => !v)}
              className="p-1.5 rounded-lg hover:bg-slate-100 text-[#64748b] hover:text-[#0A1528] transition-colors"
              title="More actions"
            >
              <MoreVertical size={16} />
            </button>
            {dropdownOpen && (
              <div className="absolute right-0 top-full mt-1 w-44 bg-white border border-[#e2e8f0] rounded-xl shadow-xl overflow-hidden z-30 py-1.5">
                {!converted && (
                  <button
                    onClick={() => { setDropdownOpen(false); markConverted(); }}
                    disabled={converting}
                    className="w-full text-left px-4 py-2 text-[13px] font-medium text-primary hover:bg-primary/5 transition-colors flex items-center gap-2 disabled:opacity-40"
                  >
                    <CheckCircle2 size={13} /> {converting ? "Saving…" : "Mark Converted"}
                  </button>
                )}
                <div className="border-t border-[#e2e8f0] my-1" />
                {role === "owner" && (
                  <button
                    onClick={() => { setDropdownOpen(false); clearData(); }}
                    disabled={clearing}
                    className="w-full text-left px-4 py-2 text-[13px] font-medium text-orange-600 hover:bg-orange-50 transition-colors flex items-center gap-2 disabled:opacity-40"
                  >
                    <Eraser size={13} /> {clearing ? "Clearing…" : "Clear Data"}
                  </button>
                )}
                <button
                  onClick={() => { setDropdownOpen(false); deleteConversation(); }}
                  disabled={deleting}
                  className="w-full text-left px-4 py-2 text-[13px] font-medium text-red-600 hover:bg-red-50 transition-colors flex items-center gap-2 disabled:opacity-40"
                >
                  <Trash2 size={13} /> {deleting ? "Deleting…" : "Delete"}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Escalation banner */}
      {hasEscalation && (
        <div className="mx-5 mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-[12px] text-red-700 flex items-center gap-2">
          <Flag size={13} className="fill-red-600 text-red-600 shrink-0" />
          <span>
            <span className="font-bold">Escalated</span>
            {" – "}
            {pendingHandover?.reason || "The customer needs a person to reply."}
            {" Reply soon so this lead isn't lost."}
          </span>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3 bg-white">
        {loading ? (
          <div className="flex items-center justify-center h-full text-[#64748b] font-body text-sm">
            Loading messages…
          </div>
        ) : messages.length === 0 && scheduled.items.length === 0 ? (
          <div className="flex items-center justify-center h-full text-[#64748b] font-body text-sm">
            No messages yet
          </div>
        ) : (
          <>
            {messages.map((msg, i) => {
              const prev = messages[i - 1];
              const showDivider = !prev || !isSameDay(new Date(msg.created_at), new Date(prev.created_at));
              return (
                <Fragment key={msg.id}>
                  {showDivider && <DateDivider dateStr={msg.created_at} />}
                  <MessageBubble msg={msg} />
                </Fragment>
              );
            })}
            <ScheduledBubbles
              items={scheduled.items}
              canChange={canReplyToConversations}
              onCancel={(id) => void scheduled.cancel(id)}
              onReschedule={scheduled.reschedule}
            />
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-[#e2e8f0] bg-white px-5 pt-3 pb-4">
        {outsideWindow && isWhatsApp && (
          <div className="mb-2 flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-amber-800">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            <p className="font-label text-[11px] leading-snug">
              Outside 24-hour window{lastInbound ? ` (last inbound ${Math.round(hoursSinceInbound)}h ago)` : ""}. Only approved templates go through reliably.
            </p>
          </div>
        )}

        {/* Quick actions row. Templates, products and payment links go out on WhatsApp only. */}
        {isWhatsApp && canReplyToConversations && (
        <div className="mb-2 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setTemplateModalOpen(true)}
            className="rounded-lg bg-[#f1f5f9] px-2.5 py-1.5 text-[11.5px] font-semibold text-[#334155] hover:bg-[#e2e8f0] flex items-center gap-1.5 transition-colors"
            title="Send an approved WhatsApp template (works any time)"
          >
            <FileText size={13} />
            Send template
          </button>

          <ShareProductMenu
            leadId={current.id}
            className="rounded-lg bg-[#f1f5f9] px-2.5 py-1.5 text-[11.5px] font-semibold text-[#334155] hover:bg-[#e2e8f0] flex items-center gap-1.5 transition-colors"
            disabledReason={outsideWindow ? "WhatsApp only delivers this within 24 hours of the customer's last message. Send a template instead." : null}
            onSent={() => void pollMessages()}
          />

          {canManageDeals && (
            <button
              type="button"
              onClick={() => setPaymentDealOpen(true)}
              className="rounded-lg bg-[#f1f5f9] px-2.5 py-1.5 text-[11.5px] font-semibold text-[#334155] hover:bg-[#e2e8f0] flex items-center gap-1.5 transition-colors"
              title="Create a deal and send its payment link on WhatsApp"
            >
              <CreditCard size={13} />
              Payment link
            </button>
          )}

          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={!canSendMedia}
            className="rounded-lg bg-[#f1f5f9] px-2.5 py-1.5 text-[11.5px] font-semibold text-[#334155] hover:bg-[#e2e8f0] flex items-center gap-1.5 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            title={canSendMedia ? "Attach a file" : "Turn AI replies off to send a file yourself"}
          >
            <Paperclip size={13} />
            Attach
          </button>
        </div>
        )}

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.doc,.xlsx,.xls,.pptx,.ppt,.txt,.csv,.png,.jpg,.jpeg,.webp,.mp3,.ogg,.wav,.aac,.amr,.mp4,.3gp,audio/webm"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) setSelectedFile(f);
            e.target.value = "";
          }}
        />

        <NewDealDialog
          open={paymentDealOpen}
          onClose={() => setPaymentDealOpen(false)}
          onCreated={() => {
            setPaymentDealOpen(false);
            void pollMessages();
          }}
          defaultLead={{ id: current.id, name: current.name ?? null, phone: current.phone ?? null }}
          defaultSource="manual"
          defaultOutcome="link"
        />

        {/* Template modal */}
        {templateModalOpen && (
          <SendTemplateModal
            leadId={current.id}
            onClose={closeTemplateModal}
            onScheduleChange={() => void scheduled.refresh()}
          />
        )}

        {selectedFile ? (
          /* File preview + send */
          <div className="space-y-2">
            <FilePreview file={selectedFile} onRemove={() => { setSelectedFile(null); setFileCaption(""); }} />
            <div className="flex items-center gap-2 bg-white border border-[#e2e8f0] rounded-2xl px-4 py-2.5 focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/15">
              <input
                value={fileCaption}
                onChange={(e) => setFileCaption(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") sendMedia(); }}
                placeholder="Add a caption (optional)…"
                disabled={sending}
                className="flex-1 bg-transparent font-body text-[13px] focus:outline-none disabled:opacity-50"
              />
              <button
                onClick={sendMedia}
                disabled={sending}
                className="h-9 w-9 rounded-xl bg-primary text-white flex items-center justify-center shrink-0 hover:bg-[var(--primary-900)] disabled:opacity-40 transition-colors"
              >
                <SendHorizontal size={16} />
              </button>
            </div>
          </div>
        ) : (
          /* Main input bar */
          <div className="relative">
            <div
              aria-hidden={replyLocked || undefined}
              className={cn(
                "rounded-2xl border border-[#e2e8f0] focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/15 flex items-center gap-2 px-4 py-2.5 transition-all",
                replyLocked && "pointer-events-none select-none blur-[3px]"
              )}
            >
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendReply(); }
                }}
                rows={1}
                disabled={!canReplyToConversations || replyLocked || sending}
                placeholder={canReplyToConversations ? "Type your reply…" : "Read-only conversation"}
                className="flex-1 bg-transparent font-body text-[13px] resize-none focus:outline-none disabled:opacity-50 max-h-28 leading-relaxed"
                style={{ minHeight: "24px" }}
                onInput={(e) => {
                  const t = e.currentTarget;
                  t.style.height = "auto";
                  t.style.height = `${Math.min(t.scrollHeight, 112)}px`;
                }}
              />

              {/* Emoji button */}
              <div className="relative" ref={emojiRef}>
                <button
                  onClick={() => setEmojiOpen(!emojiOpen)}
                  className="p-1 text-[#94a3b8] hover:text-[#0A1528] transition-colors"
                  title="Add emoji"
                >
                  <Smile size={16} />
                </button>
                {emojiOpen && (
                  <div className="absolute bottom-full right-0 z-40 mb-2 grid w-[288px] grid-cols-8 gap-0.5 rounded-xl border border-[#e2e8f0] bg-white p-2 shadow-xl">
                    {["😊", "🙏", "👍", "❤️", "🎉", "😀", "😂", "🤝", "✅", "🔥", "💐", "🌟", "📞", "📅", "💰", "🙌"].map((emoji) => (
                      <button
                        key={emoji}
                        onClick={() => {
                          setDraft(draft + emoji);
                          setEmojiOpen(false);
                        }}
                        type="button"
                        className="flex h-8 w-8 items-center justify-center rounded-lg text-[19px] leading-none transition-colors hover:bg-slate-100"
                        title={emoji}
                      >
                        {emoji}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <button
                onClick={sendReply}
                disabled={!canReplyToConversations || sending || !draft.trim()}
                title={canReplyToConversations ? "Send message" : "You have read-only access to conversations"}
                className="h-9 w-9 rounded-xl bg-primary text-white flex items-center justify-center shrink-0 hover:bg-[var(--primary-900)] disabled:cursor-not-allowed disabled:opacity-40 transition-colors"
              >
                <SendHorizontal size={16} />
              </button>
            </div>
            {replyLocked && (
              <div className="absolute inset-0 flex items-center justify-center rounded-2xl bg-white/40">
                <button
                  type="button"
                  onClick={() => setTemplateModalOpen(true)}
                  className="flex items-center gap-2 rounded-full border border-[#e2e8f0] bg-white px-4 py-2 text-xs font-bold text-[#0A1528] shadow-sm transition-colors hover:border-primary hover:text-primary"
                >
                  <Lock size={13} className="text-[#64748b]" />
                  Reply window closed · Send template
                </button>
              </div>
            )}
          </div>
        )}

        {sendError && <p className="mt-2 font-label text-xs text-red-600">{sendError}</p>}
      </div>
    </div>
  );
}
