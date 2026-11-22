"use client";
import React, { createContext, useContext, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api, AppNotification, PoolItem } from "@/lib/api";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { usePolling } from "@/hooks/usePolling";
import { fetchTodayCallbacks } from "@/app/dashboard/telecalling/lib/notes-api";
import type { CallbackJob } from "@/app/dashboard/telecalling/types";
import { Clock } from "lucide-react";
import { fetchBellAlerts } from "@/lib/bellApi";
import type { BellAlert } from "@/components/bell/alertKinds";

interface NotificationContextType {
  notifications: AppNotification[];
  /** Unread plus the last 7 days of read alerts; null until the bell has been opened once. */
  recent: BellAlert[] | null;
  loadRecent: () => Promise<void>;
  callbacks: CallbackJob[];
  pool: PoolItem[];
  markRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
  reload: () => Promise<void>;
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined);

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const { role, callerId } = useAuthRole();
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [recent, setRecent] = useState<BellAlert[] | null>(null);
  const [pool, setPool] = useState<PoolItem[]>([]);
  const [callbacks, setCallbacks] = useState<CallbackJob[]>([]);

  // Refs for tracking muted initial load to prevent flooding
  const notifiedSet = useRef<Set<string>>(new Set());
  const notifiedCallbacksSet = useRef<Set<string>>(new Set());
  const isInitialLoad = useRef(true);
  const isInitialCallbacksLoad = useRef(true);

  const loadNotificationsAndPool = useCallback(async () => {
    if (role !== "caller" && role !== "owner") return;
    try {
      const notifsRes = await api.notifications.list();
      const unread = notifsRes.data || [];
      
      if (isInitialLoad.current) {
        // Initial load: populate notifiedSet without showing toasts
        unread.forEach((n) => notifiedSet.current.add(n.id));
        isInitialLoad.current = false;
      } else {
        // Subsequent loads: toast only new unread notifications
        unread.forEach((n) => {
          if (!notifiedSet.current.has(n.id)) {
            notifiedSet.current.add(n.id);
            // Custom interactive toast layout
            const leadIdMatch = n.message.match(/\[lead_id:(.*?)\]/);
            const leadId = leadIdMatch ? leadIdMatch[1] : null;
            const handoverMatch = n.message.match(/\[handover_id:(.*?)\]/);
            const handoverId = handoverMatch ? handoverMatch[1] : null;

            const cleanDesc = n.message.replace(/\s*\[(lead_id|handover_id):.*?\]/g, "");

            if (n.type === "handover_new" && handoverId) {
              toast.error(n.title, {
                description: cleanDesc,
                action: {
                  label: "Claim",
                  onClick: async () => {
                    if (!callerId) return;
                    try {
                      await api.chatHandovers.assign(handoverId, callerId);
                      toast.success("Handover claimed!");
                    } catch {
                      toast.error("Already claimed or failed to claim");
                    }
                  }
                }
              });
            } else if (n.type === "lead_replied" && leadId) {
              toast(n.title, {
                description: cleanDesc,
                action: {
                  label: "Chat",
                  onClick: () => {
                    window.location.href = `/dashboard/conversations?lead=${leadId}`;
                  }
                }
              });
            } else {
              toast(n.title, { description: cleanDesc });
            }
          }
        });
      }
      setNotifications(unread);
    } catch (err) {
      console.error("notifications load failed", err);
    }

    if (role === "caller") {
      try {
        const poolRes = await api.notifications.pool();
        setPool(poolRes.data || []);
      } catch (err) {
        console.error("pool load failed", err);
        setPool([]);
      }
    }
  }, [role, callerId]);

  const loadDueCallbacks = useCallback(async () => {
    if (role !== "caller" || !callerId) {
      setCallbacks([]);
      return;
    }
    try {
      const todayJobs = await fetchTodayCallbacks();
      const now = new Date();
      const due = todayJobs.filter((job) => {
        if (job.lead?.assigned_to !== callerId) return false;
        return new Date(job.scheduled_for) <= now;
      });

      if (isInitialCallbacksLoad.current) {
        // Initial load: populate notifiedCallbacksSet without showing toasts
        due.forEach((cb) => notifiedCallbacksSet.current.add(cb.id));
        isInitialCallbacksLoad.current = false;
      } else {
        // Subsequent loads: toast only new due callbacks
        due.forEach((cb) => {
          if (!notifiedCallbacksSet.current.has(cb.id)) {
            notifiedCallbacksSet.current.add(cb.id);
            toast("Callback Due!", {
              description: `Time to call ${cb.lead?.name || "Lead"}`,
              icon: React.createElement(Clock, { className: "text-amber-500", size: 16 }),
            });
          }
        });
      }
      setCallbacks(due);
    } catch (err) {
      console.error("Failed to load due callbacks", err);
    }
  }, [role, callerId]);

  const reloadAll = useCallback(async () => {
    await Promise.all([loadNotificationsAndPool(), loadDueCallbacks()]);
  }, [loadNotificationsAndPool, loadDueCallbacks]);

  useEffect(() => {
    // Reset initial load refs when role/callerId changes (e.g. login/logout)
    isInitialLoad.current = true;
    isInitialCallbacksLoad.current = true;
    notifiedSet.current = new Set();
    notifiedCallbacksSet.current = new Set();
    
    reloadAll();
  }, [reloadAll, role, callerId]);

  usePolling(reloadAll, 30_000, !!role);

  const loadRecent = useCallback(async () => {
    if (role !== "caller" && role !== "owner") return;
    try {
      setRecent(await fetchBellAlerts());
    } catch (err) {
      console.error("recent alerts load failed", err);
    }
  }, [role]);

  const markRead = useCallback(async (id: string) => {
    try {
      await api.notifications.markRead(id);
      setNotifications((prev) => prev.filter((n) => n.id !== id));
      setRecent((prev) => (prev ? prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)) : prev));
    } catch (err) {
      console.error("markRead failed", err);
    }
  }, []);

  const markAllRead = useCallback(async () => {
    try {
      await api.notifications.markAllRead();
      setNotifications([]);
      setRecent((prev) => (prev ? prev.map((n) => ({ ...n, is_read: true })) : prev));
    } catch (err) {
      console.error("markAllRead failed", err);
    }
  }, []);

  return React.createElement(
    NotificationContext.Provider,
    {
      value: {
        notifications,
        recent,
        loadRecent,
        callbacks,
        pool,
        markRead,
        markAllRead,
        reload: reloadAll,
      },
    },
    children
  );
}

export function useNotifications() {
  const context = useContext(NotificationContext);
  if (context === undefined) {
    throw new Error("useNotifications must be used within a NotificationProvider");
  }
  return context;
}
