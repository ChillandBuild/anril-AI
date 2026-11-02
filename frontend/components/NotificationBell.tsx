"use client";
import { useEffect, useState } from "react";
import { Bell, X, Clock, AlertCircle, Info, CheckCircle2, CheckSquare, Smartphone } from "lucide-react";
import { useNotifications } from "@/hooks/useNotifications";
import { useRouter } from "next/navigation";
import { isPushSupported, requestAndSyncPushSubscription } from "@/lib/push";
import { toast } from "sonner";
import { api } from "@/lib/api";

export function NotificationBell() {
  const router = useRouter();
  const { notifications, callbacks, markRead, markAllRead } = useNotifications();
  const [isOpen, setIsOpen] = useState(false);
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

  const totalUnread = notifications.length + callbacks.length;
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

  const getAlertStyle = (type: string) => {
    switch (type) {
      case "system_error":
      case "missed_callback":
      case "sentiment_critical":
      case "intake_trigger_failed":
        return {
          bg: "bg-[#f8fafc]/65 hover:bg-[#f1f5f9]/65 border-[#e2e8f0]/50 border-l-4 border-l-rose-500",
          iconBg: "bg-rose-100 text-rose-600",
          icon: <AlertCircle size={14} />,
        };
      case "handover_new":
      case "callback_claimable":
      case "break_overtime":
        return {
          bg: "bg-[#f8fafc]/65 hover:bg-[#f1f5f9]/65 border-[#e2e8f0]/50 border-l-4 border-l-amber-500",
          iconBg: "bg-amber-100 text-amber-600",
          icon: <Clock size={14} />,
        };
      case "lead_assigned":
      case "lead_reassigned":
      case "callback_taken_over":
      default:
        return {
          bg: "bg-[#f8fafc]/65 hover:bg-[#f1f5f9]/65 border-[#e2e8f0]/50 border-l-4 border-l-primary",
          iconBg: "bg-primary-light text-primary",
          icon: <Info size={14} />,
        };
    }
  };

  return (
    <div className="relative">
      {/* Bell Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative flex items-center justify-center w-[34px] h-[34px] rounded-full transition-transform hover:scale-105 group"
        style={{ background: "var(--primary-400)" }}
        title="Notification Center"
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
              <h3 className="font-display text-sm font-black text-[#13284A] uppercase tracking-wider">
                Notification Center
              </h3>
              <div className="flex items-center gap-2">
                {notifications.length > 0 && (
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
                >
                  <X size={16} />
                </button>
              </div>
            </div>

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
                      <p className="mt-0.5 font-body text-[11px] leading-relaxed text-[#334155]">
                        Get notified when a new lead is assigned while Anril is in the background.
                      </p>
                    </div>
                  </div>
                </button>
              )}
              {totalUnread === 0 ? (
                <div className="py-16 text-center text-sm text-[#94a3b8] font-body flex flex-col items-center gap-2">
                  <CheckCircle2 size={32} className="text-[#d6cfc9]" />
                  All caught up!
                </div>
              ) : (
                <div className="space-y-3.5">
                  {/* Section 1: Due Callbacks */}
                  {callbacks.length > 0 && (
                    <div className="space-y-2">
                      <div className="px-1.5 text-[10px] font-black uppercase tracking-widest text-amber-600 flex items-center gap-1.5">
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
                              <p className="font-body text-[11px] text-[#475569] mt-0.5 truncate">
                                {cb.lead?.phone || "No phone"}
                              </p>
                              {cb.message_preview && (
                                <p className="font-body text-[10px] text-[#475569]/80 mt-1 italic line-clamp-1">
                                  &quot;{cb.message_preview}&quot;
                                </p>
                              )}
                            </div>
                            <button
                              onClick={handleCallbackClick}
                              className="shrink-0 self-center px-3 py-1 bg-amber-500 hover:bg-amber-600 text-white font-label text-[10px] font-bold rounded-lg transition-colors shadow-xs"
                            >
                              Call
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Separator Line */}
                  {callbacks.length > 0 && notifications.length > 0 && (
                    <div className="flex items-center py-1.5 px-1">
                      <span className="text-[10px] font-black uppercase tracking-widest text-[#94a3b8] mr-2 shrink-0">
                        Other Alerts
                      </span>
                      <div className="h-[1px] bg-[#f1f5f9] flex-1" />
                    </div>
                  )}

                  {/* Section 2: Alerts */}
                  {notifications.length > 0 && (
                    <div className="space-y-2">
                      {callbacks.length === 0 && (
                        <div className="px-1.5 text-[10px] font-black uppercase tracking-widest text-[#94a3b8] flex items-center gap-1.5">
                          <Bell size={11} />
                          System & Lead Alerts ({notifications.length})
                        </div>
                      )}
                      <div className="space-y-2">
                        {notifications.map((n) => {
                          const style = getAlertStyle(n.type);
                          // Strip metadata tags for display
                          const cleanMessage = n.message.replace(/\s*\[(lead_id|handover_id):.*?\]/g, "");
                          
                          // Custom deep-linking click behaviour
                          const leadIdMatch = n.message.match(/\[lead_id:(.*?)\]/);
                          const leadId = leadIdMatch ? leadIdMatch[1] : null;
                          const handleAlertClick = () => {
                            if (leadId) {
                              setIsOpen(false);
                              const telecallingAlert = ["lead_assigned", "lead_reassigned", "sim_call_handoff"].includes(n.type);
                              router.push(telecallingAlert ? `/dashboard/telecalling?lead_id=${leadId}` : `/dashboard/conversations?lead_id=${leadId}`);
                            }
                          };

                          return (
                            <div
                              key={n.id}
                              onClick={handleAlertClick}
                              className={`p-3.5 border rounded-2xl transition-all flex gap-3 group relative ${style.bg} ${leadId ? "cursor-pointer" : ""}`}
                            >
                              <div className="mt-0.5 shrink-0">
                                <div className={`w-7 h-7 rounded-full flex items-center justify-center ${style.iconBg}`}>
                                  {style.icon}
                                </div>
                              </div>
                              <div className="flex-1 min-w-0">
                                <p className="font-display text-xs font-black text-[#13284A] truncate">
                                  {n.title}
                                </p>
                                <p className="font-body text-[11px] mt-0.5 leading-relaxed text-[#334155]">
                                  {cleanMessage}
                                </p>
                                <p className="font-label text-[8px] text-[#94a3b8] mt-1.5">
                                  {new Date(n.created_at).toLocaleString("en-US", {
                                    month: "short",
                                    day: "numeric",
                                    hour: "2-digit",
                                    minute: "2-digit",
                                  })}
                                </p>
                              </div>
                              <button
                                onClick={(e) => handleMarkRead(n.id, e)}
                                className="shrink-0 self-center p-1.5 text-[#94a3b8] hover:text-primary hover:bg-white rounded-lg opacity-0 group-hover:opacity-100 transition-all shadow-xs"
                                title="Dismiss"
                              >
                                <CheckCircle2 size={16} />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
