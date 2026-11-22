"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Bell, X, Clock, AlertCircle, Info, CheckCircle2, CheckSquare, Smartphone, MessageCircle, Phone, IndianRupee, Package, MessageSquare } from "lucide-react";
import { useNotifications } from "@/hooks/useNotifications";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useRouter } from "next/navigation";
import {
  alertHref,
  alertKindFor,
  canSeeAlert,
  cleanMessage,
  filterByChip,
  timeAgo,
  visibleChips,
  type AlertCategory,
  type AlertIcon,
  type BellAlert,
  type ChipKey,
} from "@/components/bell/alertKinds";
import { isPushSupported, requestAndSyncPushSubscription } from "@/lib/push";
import { toast } from "sonner";
import { api } from "@/lib/api";

const ICONS: Record<AlertIcon, React.ReactNode> = {
  chat: <MessageCircle size={14} />,
  phone: <Phone size={14} />,
  money: <IndianRupee size={14} />,
  box: <Package size={14} />,
  sms: <MessageSquare size={14} />,
  alert: <AlertCircle size={14} />,
  info: <Info size={14} />,
};

const CATEGORY_STYLE: Record<AlertCategory, { border: string; iconBg: string }> = {
  needs_you: { border: "border-l-amber-500", iconBg: "bg-amber-100 text-amber-700" },
  money: { border: "border-l-emerald-500", iconBg: "bg-emerald-100 text-emerald-700" },
  stock: { border: "border-l-sky-500", iconBg: "bg-sky-100 text-sky-700" },
  calls: { border: "border-l-primary", iconBg: "bg-primary-light text-primary" },
  other: { border: "border-l-slate-400", iconBg: "bg-slate-100 text-slate-600" },
};

export function NotificationBell() {
  const router = useRouter();
  const { role, permissions } = useAuthRole();
  const { notifications, recent, loadRecent, callbacks, markRead, markAllRead } = useNotifications();
  const [isOpen, setIsOpen] = useState(false);
  const [chip, setChip] = useState<ChipKey>("all");
  const who = { isOwner: role === "owner", permissions };

  // Opening the bell loads the last 7 days (read + unread).
  const newestUnreadId = notifications[0]?.id ?? null;
  const recentRef = useRef(recent);
  recentRef.current = recent;
  useEffect(() => {
    if (isOpen) void loadRecent();
  }, [isOpen, loadRecent]);
  // A different newest unread alert that the 7-day list has not seen = something new arrived: reload.
  // Dismissing an alert yourself leaves the newest id already in the list, so it does not refetch.
  useEffect(() => {
    if (!isOpen || !newestUnreadId) return;
    if (recentRef.current?.some((n) => n.id === newestUnreadId)) return;
    void loadRecent();
  }, [isOpen, newestUnreadId, loadRecent]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen]);

  // Until the 7-day list arrives, show the unread list the app already has.
  const allAlerts: BellAlert[] = (recent ?? notifications).filter((n) => canSeeAlert(n, who));
  const chips = visibleChips(allAlerts);
  const activeChip: ChipKey = chips.some((c) => c.key === chip) ? chip : "all";
  const shownAlerts = filterByChip(allAlerts, activeChip);
  const unreadAlerts = notifications.filter((n) => canSeeAlert(n, who));
  const showCallbacks = callbacks.length > 0 && (activeChip === "all" || activeChip === "calls");
  const [pushPermission, setPushPermission] = useState<NotificationPermission | "unsupported">("unsupported");

  useEffect(() => {
    if (!isPushSupported()) {
      setPushPermission("unsupported");
      return;
    }
    setPushPermission(Notification.permission);
  }, []);

  const handleMarkRead = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    markRead(id);
  };

  const handleMarkAllRead = async () => {
    await markAllRead();
  };

  const handleCallbackClick = () => {
    setIsOpen(false);
    router.push("/dashboard/telecalling");
  };

  const totalUnread = unreadAlerts.length + callbacks.length;

  const handleAction = (n: BellAlert, href: string) => {
    if (!n.is_read) void markRead(n.id);
    setIsOpen(false);
    router.push(href);
  };
  const canEnablePush = pushPermission === "default";

  const handleEnablePush = async () => {
    try {
      const result = await requestAndSyncPushSubscription();
      if (result.enabled) {
        setPushPermission("granted");
        toast.success("Mobile push notifications enabled");
      } else {
        setPushPermission(Notification.permission);
        if (result.reason === "missing_key") {
          const status = await api.push.status().catch(() => null);
          if (status && !status.public_key_configured && !status.private_key_configured) {
            toast.info("Push alerts are not configured on the server yet. In-app notifications still work.");
          } else {
            toast.info("Push alerts need server setup. In-app notifications still work.");
          }
        } else {
          toast.error("Push permission was not granted");
        }
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to enable push notifications");
    }
  };

  return (
    <div className="relative">
      {/* Bell Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative flex items-center justify-center w-[34px] h-[34px] rounded-full transition-transform hover:scale-105 group"
        style={{ background: "var(--primary-400)" }}
        title="Alerts"
        aria-label={totalUnread > 0 ? `Alerts, ${totalUnread} new` : "Alerts"}
        aria-expanded={isOpen}
      >
        <Bell size={16} className="text-[#0A1528]" />
        {totalUnread > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[22px] h-[22px] px-1.5 bg-[#f0643f] text-white text-[10px] font-black rounded-full flex items-center justify-center ring-4 ring-white shadow-sm animate-bounce-short">
            {totalUnread > 99 ? "99+" : totalUnread}
          </span>
        )}
      </button>

      {/* Dropdown Panel */}
      {isOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          <div className="fixed inset-x-3 top-[calc(4.5rem+env(safe-area-inset-top))] bottom-[calc(5.25rem+env(safe-area-inset-bottom))] z-50 flex flex-col overflow-hidden rounded-3xl border border-[#e2e8f0]/60 bg-white/95 shadow-2xl backdrop-blur-xl animate-in fade-in slide-in-from-top-4 duration-200 md:absolute md:inset-auto md:right-0 md:top-full md:mt-3 md:max-h-[80vh] md:w-96">
            {/* Header */}
            <div className="px-5 py-4 bg-gradient-to-br from-primary-light/65 to-primary-50/65 border-b border-[#f1f5f9] flex items-center justify-between">
              <h3 className="font-display text-sm font-black text-[#13284A]">
                Alerts{totalUnread > 0 ? ` · ${totalUnread} new` : ""}
              </h3>
              <div className="flex items-center gap-2">
                {unreadAlerts.length > 0 && (
                  <button
                    onClick={handleMarkAllRead}
                    className="p-1.5 text-xs text-primary hover:text-primary-dark hover:bg-primary-light/50 rounded-xl transition-all flex items-center gap-1 font-bold"
                    title="Mark all as read"
                  >
                    <CheckSquare size={13} />
                    Mark all read
                  </button>
                )}
                <button
                  onClick={() => setIsOpen(false)}
                  className="p-1.5 text-[#94a3b8] hover:text-[#1e293b] rounded-xl hover:bg-[#f1f5f9]/50 transition-colors"
                  aria-label="Close alerts"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Chips */}
            {chips.length > 1 && (
              <div className="flex flex-wrap gap-1.5 border-b border-[#f1f5f9] px-4 py-2.5" role="group" aria-label="Filter alerts">
                {chips.map((c) => (
                  <button
                    key={c.key}
                    type="button"
                    aria-pressed={activeChip === c.key}
                    onClick={() => setChip(c.key)}
                    className={`rounded-full px-3 py-1 text-xs font-bold transition-colors ${
                      activeChip === c.key
                        ? "bg-[#13284A] text-white"
                        : "bg-[#f1f5f9] text-[#334155] hover:bg-[#e2e8f0]"
                    }`}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            )}

            {/* Combined Content List */}
            <div className="overflow-y-auto flex-1 p-3.5 space-y-3">
              {canEnablePush && (
                <button
                  type="button"
                  onClick={handleEnablePush}
                  className="w-full rounded-2xl border border-primary-muted bg-primary-light/60 p-3 text-left transition hover:bg-primary-light"
                >
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-white text-primary">
                      <Smartphone size={16} />
                    </div>
                    <div>
                      <p className="font-display text-xs font-black text-[#13284A]">Enable phone alerts</p>
                      <p className="mt-0.5 font-body text-xs leading-relaxed text-[#334155]">
                        Get notified when a new lead is assigned while Anril is in the background.
                      </p>
                    </div>
                  </div>
                </button>
              )}
              {shownAlerts.length === 0 && !showCallbacks ? (
                <div className="py-16 text-center text-sm text-[#94a3b8] font-body flex flex-col items-center gap-2">
                  <CheckCircle2 size={32} className="text-[#d6cfc9]" />
                  {activeChip === "all" ? "All caught up!" : "Nothing here right now."}
                </div>
              ) : (
                <div className="space-y-3.5">
                  {/* Section 1: Due Callbacks */}
                  {showCallbacks && (
                    <div className="space-y-2">
                      <div className="px-1.5 text-xs font-black uppercase tracking-widest text-amber-600 flex items-center gap-1.5">
                        <Clock size={11} />
                        Due Callbacks ({callbacks.length})
                      </div>
                      <div className="space-y-2">
                        {callbacks.map((cb) => (
                          <div
                            key={cb.id}
                            onClick={handleCallbackClick}
                            className="p-3.5 bg-[#f8fafc]/65 hover:bg-[#f1f5f9]/65 border border-[#e2e8f0]/50 border-l-4 border-l-amber-500 rounded-2xl transition-all flex gap-3 cursor-pointer group"
                          >
                            <div className="mt-0.5 shrink-0">
                              <div className="w-7 h-7 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center">
                                <Clock size={13} />
                              </div>
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="font-display text-xs font-black text-[#13284A] truncate">
                                {cb.lead?.name || "Unnamed Lead"}
                              </p>
                              <p className="font-body text-xs text-[#475569] mt-0.5 truncate">
                                {cb.lead?.phone || "No phone"}
                              </p>
                              {cb.message_preview && (
                                <p className="font-body text-xs text-[#475569]/80 mt-1 italic line-clamp-1">
                                  &quot;{cb.message_preview}&quot;
                                </p>
                              )}
                            </div>
                            <button
                              onClick={handleCallbackClick}
                              className="shrink-0 self-center px-3 py-1 bg-amber-500 hover:bg-amber-600 text-white font-label text-xs font-bold rounded-lg transition-colors shadow-xs"
                            >
                              Call
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Separator Line */}
                  {showCallbacks && shownAlerts.length > 0 && (
                    <div className="flex items-center py-1.5 px-1">
                      <span className="text-xs font-black uppercase tracking-widest text-[#94a3b8] mr-2 shrink-0">
                        Other Alerts
                      </span>
                      <div className="h-[1px] bg-[#f1f5f9] flex-1" />
                    </div>
                  )}

                  {/* Section 2: Alerts */}
                  {shownAlerts.length > 0 && (
                    <div className="space-y-2">
                      <div className="space-y-2">
                        {shownAlerts.map((n) => {
                          const kind = alertKindFor(n.type);
                          const style = CATEGORY_STYLE[kind.category];
                          const href = alertHref(n);
                          return (
                            <div
                              key={n.id}
                              onClick={href ? () => handleAction(n, href) : undefined}
                              className={`p-3.5 border border-[#e2e8f0]/50 border-l-4 ${style.border} rounded-2xl transition-all flex gap-3 group relative bg-[#f8fafc]/65 hover:bg-[#f1f5f9]/65 ${
                                href ? "cursor-pointer" : ""
                              } ${n.is_read ? "opacity-60" : ""}`}
                            >
                              <div className="mt-0.5 shrink-0">
                                <div className={`w-7 h-7 rounded-full flex items-center justify-center ${style.iconBg}`}>
                                  {ICONS[kind.icon]}
                                </div>
                              </div>
                              <div className="flex-1 min-w-0">
                                <p className="font-display text-sm font-black text-[#13284A] break-words">
                                  {n.title}
                                </p>
                                <p className="font-body text-xs mt-0.5 leading-relaxed text-[#334155] break-words">
                                  {cleanMessage(n.message)}
                                </p>
                                <p className="font-body text-xs text-[#64748b] mt-1">
                                  {kind.module} · {timeAgo(n.created_at)}
                                </p>
                                {kind.action && href && (
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleAction(n, href);
                                    }}
                                    className="mt-2 inline-flex min-h-[32px] items-center rounded-lg bg-[#13284A] px-3 py-1 text-xs font-bold text-white transition-colors hover:bg-[#1e3a6b]"
                                  >
                                    {kind.action.label} ›
                                  </button>
                                )}
                              </div>
                              {!n.is_read && (
                                <button
                                  onClick={(e) => handleMarkRead(n.id, e)}
                                  className="shrink-0 self-start p-1.5 text-[#94a3b8] hover:text-primary hover:bg-white rounded-lg opacity-100 md:opacity-0 md:group-hover:opacity-100 focus-visible:opacity-100 transition-all shadow-xs"
                                  title="Dismiss"
                                  aria-label="Mark as read"
                                >
                                  <CheckCircle2 size={16} />
                                </button>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="border-t border-[#f1f5f9] px-4 py-2.5 text-xs text-[#64748b]">
              Choose which alerts you get in{" "}
              <Link
                href="/dashboard/settings/notifications"
                onClick={() => setIsOpen(false)}
                className="font-bold text-primary underline-offset-2 hover:underline"
              >
                Settings › Alerts &amp; automations
              </Link>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
