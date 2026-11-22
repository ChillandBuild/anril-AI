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
import { RecordPaymentDialog } from "@/components/chats/RecordPaymentDialog";
import type { Option } from "@/components/chats/inboxFilters";
import { Select } from "@/components/ui/Select";
import { fetchHandovers, resolveHandover, type Handover } from "@/lib/escalations";
import {
  CheckCircle2,
  AlertTriangle, Pencil, Trash2,
  FileText, Image as ImageIcon,
  Music, Video, Download, X, Eraser, MoreVertical,
  ArrowLeft, Check, CheckCheck, Smile, SendHorizontal, Paperclip, CreditCard, Lock,
  PanelRightOpen, PanelRightClose, UserRound, Loader2,
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
// ─── Real delivery ticks, from WhatsApp's receipts ─────────────────────────────
function DeliveryTicks({ msg, onDark }: { msg: Message; onDark: boolean }) {
  const status = msg.delivery_status;
  if (status === "failed") {
    return (
      <span className={cn("inline-flex items-center gap-0.5 font-semibold", onDark ? "text-amber-200" : "text-red-500")} title={msg.delivery_error_title || "Not delivered"}>
        <AlertTriangle size={11} /> Not delivered
      </span>
    );
  }
  if (status === "read") {
    return <CheckCheck size={13} className={onDark ? "text-sky-200" : "text-sky-500"} aria-label="Read" />;
  }
  if (status === "delivered") return <CheckCheck size={13} aria-label="Delivered" />;
  return <Check size={13} aria-label="Sent" />;
}

const MessageBubble = memo(function MessageBubble({ msg, myUserId }: { msg: Message; myUserId: string | null }) {
  const isOutbound = msg.direction === "outbound";
  const isAi = isOutbound && msg.is_ai_generated;
  const isMine = Boolean(myUserId && msg.sent_by_user_id === myUserId);
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
        {isOutbound && !isAi && msg.sent_by_name && (
          <p className="mb-0.5 flex items-center gap-1 text-[10.5px] font-bold text-white/85">
            <UserRound size={11} strokeWidth={2.5} /> {msg.sent_by_name}{isMine && <span className="font-semibold text-white/70"> (you)</span>}
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
          <span>{new Date(msg.created_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}</span>
          {isOutbound && <DeliveryTicks msg={msg} onDark={!isAi} />}
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
/** "from Google Ads · summer_sale" / "from Meta ad · …" / "from QR · …": the server sends came_from. */
function cameFromLabel(lead: Lead): string | null {
  const sent = lead.came_from;
  if (sent) return sent;
  if (lead.ad_campaign_name) return `from ${lead.ad_campaign_name}`;
  return lead.ad_campaign_id ? "from an ad" : null;
}

export function ChatThread({
  lead,
  team = [],
  onDeleted,
  onLeadUpdate,
  onBack,
  detailsOpen = false,
  onToggleDetails,
}: {
  lead: Lead;
  /** Teammates, for the assign dropdown and Record payment's Sold by. */
  team?: Option[];
  onDeleted?: (id: string) => void;
  onLeadUpdate?: (updated: Lead) => void;
  onBack?: () => void;
  detailsOpen?: boolean;
  onToggleDetails?: () => void;
}) {
  const { role, permissions, callerId } = useAuthRole();
  const masterAiEnabled = useMasterAiEnabled();
  const canReplyToConversations = role === "owner" || permissions.includes("conversations.reply");
  const canManageDeals = role === "owner" || permissions.includes("deals.manage");
  const [paymentDealOpen, setPaymentDealOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [current, setCurrent] = useState<Lead>(lead);
  const hasEscalation = Boolean(current.needs_human_attention || current.needs_human_intervention);
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

  // Header + handover state
  const [handovers, setHandovers] = useState<Handover[]>([]);
  const [assigning, setAssigning] = useState(false);
  const [claiming, setClaiming] = useState(false);
  const [myUserId, setMyUserId] = useState<string | null>(null);
  // "Teach the Anril AI": offered to the owner after they answer a chat the AI handed over.
  const [teach, setTeach] = useState<{ when: string; say: string } | null>(null);
  const [teachSaving, setTeachSaving] = useState(false);
  const pendingHandover = handovers.find((h) => h.lead_id === current.id);
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);
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
    setTeach(null);
  }, [lead.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Who "you" is, so your own replies read "(you)".
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setMyUserId(data.session?.user.id ?? null)).catch(() => {});
  }, []);

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

  // Re-read on each lead so the handover reason belongs to the chat on screen.
  useEffect(() => {
    fetchHandovers().then(setHandovers).catch(() => {});
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

  // A blocked person gets nothing from us, so the send box gives way to a plain Unblock button.
  const [unblocking, setUnblocking] = useState(false);
  async function unblock() {
    setUnblocking(true);
    try {
      const updated = await api.leads.block(current.id);
      const next = { ...current, ...updated };
      setCurrent(next);
      onLeadUpdate?.(next);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't unblock this person");
    } finally { setUnblocking(false); }
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

  async function assignTo(callerIdToSet: string) {
    setAssigning(true);
    try {
      const updated = await api.leads.assign(current.id, callerIdToSet || null);
      const next = { ...current, ...updated, assigned_to: callerIdToSet || null };
      setCurrent(next);
      onLeadUpdate?.(next);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't change who handles this chat");
    } finally { setAssigning(false); }
  }

  // "I'll reply": take the handover (so teammates see it's yours) and jump to the reply box.
  async function claimHandover() {
    textareaRef.current?.focus();
    if (!pendingHandover || !callerId || pendingHandover.assigned_to === callerId) return;
    setClaiming(true);
    try {
      await api.chatHandovers.assign(pendingHandover.id, callerId);
      setHandovers((prev) => prev.map((h) => (h.id === pendingHandover.id ? { ...h, assigned_to: callerId } : h)));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't take this chat");
    } finally { setClaiming(false); }
  }

  async function offerTeach() {
    try {
      const { suggestion } = await api.chats.teachSuggestion(lead.id);
      if (suggestion) setTeach(suggestion);
    } catch { /* teaching is optional; a failed suggestion just doesn't show */ }
  }

  async function saveTeach() {
    if (!teach || !teach.say.trim()) return;
    setTeachSaving(true);
    try {
      await api.chats.teach(teach.when, teach.say.trim());
      toast.success("Saved. The Anril AI will answer this itself next time.");
      setTeach(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save the answer");
    } finally { setTeachSaving(false); }
  }

  async function sendReply() {
    const text = draft.trim();
    if (!canReplyToConversations || replyLocked || current.blocked_at || !text || sending) return;
    setSending(true);
    setSendError(null);
    // Answering a chat the AI handed over is the moment to teach it (owner only).
    const answeringHandover = role === "owner" && hasEscalation;
    try {
      const sentMsg = await api.leads.sendMessage(lead.id, text);
      setMessages((prev) => {
        const msgId = sentMsg.id || (sentMsg as unknown as Record<string, unknown>).sid || Date.now().toString();
        if (prev.some((m) => m.id === msgId)) return prev;
        return [...prev, sentMsg as Message];
      });
      setDraft("");
      if (answeringHandover) void offerTeach();
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
  const replyWindowLeft = (() => {
    if (loading || !isWhatsApp || outsideWindow || !lastInbound) return null;
    const minsLeft = Math.floor((24 - hoursSinceInbound) * 60);
    if (minsLeft >= 60) return `${Math.floor(minsLeft / 60)}h`;
    return `${Math.max(1, minsLeft)}m`;
  })();


  return (
    <div className="flex-1 flex flex-col h-full min-w-0">
      {/* Header */}
      {/* Same 68px band as the chat list header and the customer panel header. */}
      <div className="flex h-[68px] shrink-0 items-center gap-3 border-b border-[#e2e8f0] bg-white px-5">
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

        {/* Name, then phone · channel · ad */}
        <div className="min-w-[120px] flex-1">
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
              className="w-full max-w-[260px] font-display text-[15px] font-bold text-[#0A1528] bg-slate-50 px-2 py-0.5 rounded border border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          ) : (
            <button
              onClick={() => { setNameDraft(current.name || ""); setEditingName(true); }}
              className="group flex max-w-full items-center gap-1.5"
              title="Click to rename"
            >
              <span className="font-display text-[15px] font-bold leading-tight text-[#0A1528] truncate">
                {current.name || formatPhone(current.phone) || "Unknown"}
              </span>
              <Pencil size={13} className="opacity-0 group-hover:opacity-50 text-[#94a3b8] shrink-0" />
            </button>
          )}
          <p className="mt-0.5 font-label text-[11.5px] text-[#64748b] flex items-center gap-1 min-w-0">
            {/* The phone is already the title when there's no name, so don't repeat it. */}
            {current.phone && current.name && <span className="whitespace-nowrap">{formatPhone(current.phone)}</span>}
            {current.phone && current.name && <span className="text-[#cbd5e1]">·</span>}
            <span className="whitespace-nowrap">{CHANNEL_LABEL[getChannel(current.source)]}</span>
            {cameFromLabel(current) ? (
              <>
                <span className="text-[#cbd5e1]">·</span>
                <span className="truncate">{cameFromLabel(current)}</span>
              </>
            ) : null}
          </p>
        </div>

        {/* Right side controls */}
        <div className="ml-auto flex items-center gap-2">
          {/* Who handles this chat. Only the owner can change it (the API is owner-only). */}
          <div
            className="hidden w-[132px] shrink-0 md:block"
            title={role === "owner" ? "Who handles this chat" : "Only the owner can change who handles a chat"}
          >
            <Select
              size="sm"
              value={current.assigned_to ?? ""}
              onChange={(v) => void assignTo(v)}
              disabled={role !== "owner" || assigning}
              aria-label="Assigned to"
              className="rounded-xl"
              options={[
                { value: "", text: "Unassigned", label: <span className="flex items-center gap-1.5 text-[#64748b]"><UserRound size={13} />Unassigned</span> },
                ...team.map((t) => ({ value: t.value, text: t.label, label: <span className="flex items-center gap-1.5"><UserRound size={13} className="text-primary" />{t.label}</span> })),
                ...(current.assigned_to && !team.some((t) => t.value === current.assigned_to)
                  ? [{ value: current.assigned_to, text: "A teammate", label: <span className="flex items-center gap-1.5"><UserRound size={13} />A teammate</span> }]
                  : []),
              ]}
            />
          </div>

          {/* AI agent switch */}
          <label
            className={cn("flex items-center gap-2 rounded-xl px-2 py-1.5", !masterAiEnabled && "opacity-50")}
            title={masterAiEnabled ? (aiEnabled ? "The AI agent replies in this chat" : "The AI agent is off for this chat") : "AI is off for your whole account — turn it on in Settings → Auto-Reply"}
          >
            <span className="hidden text-[12.5px] font-semibold text-[#334155] 2xl:inline">AI agent</span>
            <SwitchPill on={masterAiEnabled && aiEnabled} disabled={!masterAiEnabled} onChange={() => toggleAI()} size="sm" aria-label="AI agent" />
          </label>

          {/* Customer panel toggle (wide screens, where the panel fits) */}
          {onToggleDetails && (
            <button
              onClick={onToggleDetails}
              aria-pressed={detailsOpen}
              aria-label={detailsOpen ? "Hide customer panel" : "Show customer panel"}
              title={detailsOpen ? "Hide customer panel" : "Show customer panel"}
              className={cn(
                "hidden h-9 w-9 items-center justify-center rounded-xl border transition-colors xl:flex",
                detailsOpen
                  ? "border-primary/30 bg-primary-light text-primary"
                  : "border-[#e2e8f0] text-[#64748b] hover:bg-slate-50 hover:text-[#0A1528]"
              )}
            >
              {detailsOpen ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}
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
                  <MessageBubble msg={msg} myUserId={myUserId} />
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

      {/* The AI handed this chat over: say why, and let a person take it. */}
      {hasEscalation && !teach && (
        <div className="flex items-center gap-3 border-t border-amber-200 bg-amber-50 px-5 py-1.5">
          <p className="min-w-0 flex-1 text-[12.5px] leading-snug text-amber-900">
            <span className="mr-1">🙋</span>
            <span className="font-bold">The AI agent needs you:</span>{" "}
            {pendingHandover?.reason || current.escalation_reason || "the customer is waiting for a person."}
          </p>
          {canReplyToConversations && (
            callerId && pendingHandover && pendingHandover.assigned_to !== callerId ? (
              <button
                type="button"
                onClick={() => void claimHandover()}
                disabled={claiming}
                className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3.5 text-[12px] font-bold text-white shadow-sm hover:bg-[var(--primary-900)] disabled:opacity-50"
              >
                {claiming && <Loader2 size={13} className="animate-spin" />} I&apos;ll reply
              </button>
            ) : (
              <button
                type="button"
                onClick={markResolved}
                disabled={resolvingHandover}
                title="The customer has what they needed: close this handover"
                className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3.5 text-[12px] font-bold text-amber-900 hover:bg-amber-100 disabled:opacity-50"
              >
                <Check size={14} /> {resolvingHandover ? "Closing…" : "Mark done"}
              </button>
            )
          )}
        </div>
      )}

      {/* Teach the Anril AI: turn the reply just sent into an answer it can give next time. */}
      {teach && (
        <div className="border-t border-sky-200 bg-sky-50 px-5 py-3">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-[12.5px] leading-snug text-[#0c4a6e]">
                <span className="mr-1">🤖</span>
                <span className="font-bold">Teach the Anril AI?</span> Next time {teach.when}, it will say:
              </p>
              <input
                value={teach.say}
                onChange={(e) => setTeach({ ...teach, say: e.target.value })}
                onKeyDown={(e) => { if (e.key === "Enter") void saveTeach(); }}
                maxLength={400}
                aria-label="What the Anril AI will say"
                className="mt-2 h-10 w-full rounded-xl border border-sky-200 bg-white px-3 text-[13px] text-[#0A1528] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15"
              />
            </div>
            <div className="flex w-[112px] shrink-0 flex-col gap-1.5">
              <button
                type="button"
                onClick={() => void saveTeach()}
                disabled={teachSaving || !teach.say.trim()}
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-xl bg-primary text-[12.5px] font-bold text-white shadow-sm hover:bg-[var(--primary-900)] disabled:opacity-50"
              >
                {teachSaving && <Loader2 size={13} className="animate-spin" />} Save answer
              </button>
              <button
                type="button"
                onClick={() => setTeach(null)}
                disabled={teachSaving}
                className="h-9 rounded-xl border border-sky-200 bg-white text-[12.5px] font-semibold text-[#334155] hover:bg-sky-100"
              >
                Not now
              </button>
            </div>
          </div>
          <p className="mt-2 text-[11px] text-[#64748b]">
            Only the owner can save answers. It&apos;s added to Anril Setup › Teach &amp; offers, where you can change or delete it.
          </p>
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-[#e2e8f0] bg-white px-5 pt-3 pb-4">
        {!current.blocked_at && outsideWindow && isWhatsApp && (
          <div className="mb-2 flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-amber-800">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            <p className="font-label text-[11px] leading-snug">
              Outside 24-hour window{lastInbound ? ` (last inbound ${Math.round(hoursSinceInbound)}h ago)` : ""}. Only approved templates go through reliably.
            </p>
          </div>
        )}

        {/* Quick actions row. Templates, products and payment links go out on WhatsApp only. */}
        {!current.blocked_at && isWhatsApp && canReplyToConversations && (
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
              title="Record a payment or send a payment link on WhatsApp"
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

        <RecordPaymentDialog
          open={paymentDealOpen}
          onClose={() => setPaymentDealOpen(false)}
          lead={current}
          team={team}
          defaultMethod="link"
          defaultSoldBy={current.assigned_to ?? callerId}
          onRecorded={() => void pollMessages()}
        />

        {/* Template modal */}
        {templateModalOpen && (
          <SendTemplateModal
            leadId={current.id}
            onClose={closeTemplateModal}
            onScheduleChange={() => void scheduled.refresh()}
          />
        )}

        {current.blocked_at ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#e2e8f0] bg-[#f8fafc] px-4 py-3">
            <p className="text-[13px] font-medium text-[#334155]">This person is blocked. Unblock to reply.</p>
            {canReplyToConversations && (
              <button
                type="button"
                onClick={() => void unblock()}
                disabled={unblocking}
                className="h-9 rounded-xl bg-primary px-4 text-[13px] font-semibold text-white transition-colors hover:bg-[var(--primary-900)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {unblocking ? "Unblocking…" : "Unblock"}
              </button>
            )}
          </div>
        ) : selectedFile ? (
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
                ref={textareaRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendReply(); }
                }}
                rows={1}
                disabled={!canReplyToConversations || replyLocked || sending}
                placeholder={canReplyToConversations ? "Type a message…" : "Read-only conversation"}
                className="flex-1 bg-transparent font-body text-[13px] resize-none focus:outline-none disabled:opacity-50 max-h-28 leading-relaxed"
                style={{ minHeight: "24px" }}
                onInput={(e) => {
                  const t = e.currentTarget;
                  t.style.height = "auto";
                  t.style.height = `${Math.min(t.scrollHeight, 112)}px`;
                }}
              />

              {/* WhatsApp's free-reply window: how long a normal message still goes through. */}
              {replyWindowLeft && (
                <span
                  className="hidden shrink-0 whitespace-nowrap text-[11.5px] text-[#94a3b8] sm:inline"
                  title="WhatsApp lets you send normal messages for 24 hours after the customer's last message. After that, only templates."
                >
                  free to reply for {replyWindowLeft}
                </span>
              )}

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
