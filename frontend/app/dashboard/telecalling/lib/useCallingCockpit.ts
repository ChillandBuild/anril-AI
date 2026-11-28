"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api, Lead, CallLog, Message, TelecallingConfig, type CatalogItem, type WrapupContext } from "@/lib/api";
import type { NotesResponse, CallbackJob } from "../types";
import { useActiveCall } from "../../contexts/ActiveCallContext";
import { fetchNotes, fetchTodayCallbacks, saveNote, createCallback } from "./notes-api";
import { defaultDialMode, type DialMode } from "./dialCheck";
import { isMobileDialSurface, openNativeDialer } from "./sim-dialer";
import { formatIstWhen, fromIstInputs, toIstInputs } from "@/lib/call-wrapup";
import { applyContext, draftError, draftToPayload, emptyDraft, type WrapupDraft } from "./wrapup-draft";
import type { LeadDetailPanelProps } from "../components/LeadDetailPanel";

interface UseCallingCockpitArgs {
  /** Who the call dials as. null = current user (admin self) → sent as undefined. */
  callerId: string | null;
  /** Show the blocking "pending wrap-ups" overlay (telecaller discipline gate). */
  blockingWrapups: boolean;
  /** Refresh the page's own lead queue after a dial / outcome / release. */
  refreshQueue: () => void;
}

/**
 * Shared calling engine for the telecaller cockpit and the admin dialer.
 * Owns lead-profile loading, the accidental-dial guard, live-call polling,
 * the AI pre-call brief, quick notes/callbacks, and the mandatory wrap-up.
 * The ONLY per-surface differences are the lead queue (rendered by each page),
 * the caller identity (`callerId`), and whether the wrap-up gate blocks
 * (`blockingWrapups`).
 */
export function useCallingCockpit({ callerId, blockingWrapups, refreshQueue }: UseCallingCockpitArgs) {
  const { activeCall: activeCallCtx, setActiveCall: setActiveCallCtx } = useActiveCall();

  // refreshQueue can change identity per render; ref keeps effects stable.
  const refreshQueueRef = useRef(refreshQueue);
  refreshQueueRef.current = refreshQueue;

  // Selected lead profile
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [selectedLeadNotes, setSelectedLeadNotes] = useState<NotesResponse | null>(null);
  const [selectedLeadMessages, setSelectedLeadMessages] = useState<Message[]>([]);
  const [selectedLeadCallLogs, setSelectedLeadCallLogs] = useState<CallLog[]>([]);
  const [selectedLeadBrief, setSelectedLeadBrief] = useState<{ brief: string; opener: string } | null>(null);
  const [briefLoading, setBriefLoading] = useState(false);
  const [selectedLeadLoading, setSelectedLeadLoading] = useState(false);
  const [selectedCallbackJobId, setSelectedCallbackJobId] = useState<string | null>(null);
  const [activeProfileTab, setActiveProfileTab] = useState<"overview" | "notes" | "attribution" | "script">("overview");

  // Callbacks (auto-link + queue counts)
  const [todayCallbacks, setTodayCallbacks] = useState<CallbackJob[]>([]);

  // Dialing
  const [dialing, setDialing] = useState<string | null>(null);
  const [confirmRelease, setConfirmRelease] = useState<string | null>(null);
  const [manualPhone, setManualPhone] = useState("");
  const [manualDialing, setManualDialing] = useState(false);
  const [dialingNext, setDialingNext] = useState(false);

  // Quick note / callback picker
  const [quickNoteTitle, setQuickNoteTitle] = useState("");
  const [quickNoteContent, setQuickNoteContent] = useState("");
  const [quickNoteSaving, setQuickNoteSaving] = useState(false);
  const [quickNoteTags, setQuickNoteTags] = useState<string[]>([]);
  const [quickNotePinned, setQuickNotePinned] = useState(false);
  const [showCallbackPicker, setShowCallbackPicker] = useState(false);
  const [callbackDate, setCallbackDate] = useState("");
  const [callbackTime, setCallbackTime] = useState("");

  // Accidental-dial guard
  const [dialCountdown, setDialCountdown] = useState<number | null>(null);
  const [dialTarget, setDialTarget] = useState<{ leadId?: string; lead?: Lead; phone?: string; viaPad?: boolean } | null>(null);

  // Live call card
  const [callDuration, setCallDuration] = useState<number>(0);
  const [callStatus, setCallStatus] = useState<"ringing" | "connected" | "ended" | null>(null);
  const [callingProvider, setCallingProvider] = useState<"telecmi" | "sim_basic">("telecmi");
  // Manual Dial's Office number / My SIM choice: null until the person picks (or the check sets it), per screen session.
  const [dialMode, setDialMode] = useState<DialMode | null>(null);
  const [officeReady, setOfficeReady] = useState(true);
  const padProvider: "telecmi" | "sim_basic" = (dialMode ?? defaultDialMode(null, callingProvider)) === "sim" ? "sim_basic" : "telecmi";
  const [activeCallProvider, setActiveCallProvider] = useState<"telecmi" | "sim_basic">("telecmi");
  const [simHandoffLead, setSimHandoffLead] = useState<Lead | null>(null);
  const [simHandoffSending, setSimHandoffSending] = useState(false);

  // Mandatory wrap-up (two taps, identical for SIM and cloud)
  const [showWrapupModal, setShowWrapupModal] = useState(false);
  const [wrapupDraft, setWrapupDraft] = useState<WrapupDraft>(emptyDraft);
  const [wrapupContext, setWrapupContext] = useState<WrapupContext | null>(null);
  const [catalogItems, setCatalogItems] = useState<CatalogItem[]>([]);
  const catalogLoaded = useRef(false);
  const [wrapupSaving, setWrapupSaving] = useState(false);
  const [wrapupStartedAt, setWrapupStartedAt] = useState("");
  const [wrapupEndedAt, setWrapupEndedAt] = useState("");
  const [pendingWrapups, setPendingWrapups] = useState<CallLog[]>([]);

  // Live script panel
  const [telecallingConfig, setTelecallingConfig] = useState<TelecallingConfig | null>(null);
  const [scriptExpanded, setScriptExpanded] = useState(true);

  const loadCallbacks = useCallback(() => {
    fetchTodayCallbacks().then(setTodayCallbacks).catch(() => {});
  }, []);

  const loadPendingWrapups = useCallback(async () => {
    if (!blockingWrapups) return;
    try {
      setPendingWrapups(await api.calls.getPendingWrapups());
    } catch {
      // transient — next load retries
    }
  }, [blockingWrapups]);

  const loadTelecallingConfig = useCallback(async () => {
    try {
      const [config, assignmentMode] = await Promise.all([
        api.settings.getTelecallingConfig().catch(() => null),
        api.calls.assignmentMode().catch(() => null),
      ]);
      if (config) setTelecallingConfig(config);
      setCallingProvider(assignmentMode?.calling_provider ?? (config?.calling_provider as "telecmi" | "sim_basic" | undefined) ?? "telecmi");
      if (assignmentMode?.office_ready !== undefined) setOfficeReady(assignmentMode.office_ready);
    } catch (err) {
      console.error("Failed to load telecalling config:", err);
    }
  }, []);

  // SIM call timing is entered as tenant-local IST, whatever timezone the telecaller's device is
  // set to -- these always go through call-wrapup.ts's IST helpers, never the machine's own zone.
  function toDateTimeInput(date: Date) {
    const { date: d, time: t } = toIstInputs(date);
    return `${d}T${t}`;
  }

  function inputToIso(value: string) {
    if (!value) return undefined;
    const [d, t] = value.split("T");
    return fromIstInputs(d, t)?.toISOString();
  }

  function secondsBetween(start: string, end: string) {
    const startIso = inputToIso(start);
    const endIso = inputToIso(end);
    if (!startIso || !endIso) return undefined;
    const diff = Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000);
    return Number.isFinite(diff) ? Math.max(0, diff) : undefined;
  }

  function primeSimWrapup(startedAt: Date) {
    setWrapupStartedAt(toDateTimeInput(startedAt));
    setWrapupEndedAt(toDateTimeInput(new Date()));
    setCallStatus("ended");
    setShowWrapupModal(true);
  }


  // Initial cockpit-owned data (queue is loaded by the page itself).
  useEffect(() => {
    loadCallbacks();
    loadPendingWrapups();
    loadTelecallingConfig();
  }, [loadCallbacks, loadPendingWrapups, loadTelecallingConfig]);

  // Refresh callbacks every 5 minutes (parity with the telecaller cockpit).
  useEffect(() => {
    const id = setInterval(loadCallbacks, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [loadCallbacks]);

  // Blocking wrap-ups: poll while the gate is on so a stale tab can't escape it.
  useEffect(() => {
    if (!blockingWrapups) return;
    const id = setInterval(loadPendingWrapups, 5000);
    // Reopening/refocusing the app must lock immediately, not after the next tick.
    const onVisible = () => {
      if (document.visibilityState === "visible") loadPendingWrapups();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", loadPendingWrapups);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", loadPendingWrapups);
    };
  }, [blockingWrapups, loadPendingWrapups]);

  async function generatePreCallBrief(leadId: string, force = false) {
    setBriefLoading(true);
    try {
      setSelectedLeadBrief(await api.leads.preCallBrief(leadId, force));
    } catch {
      toast.error("Failed to generate brief");
    } finally {
      setBriefLoading(false);
    }
  }

  async function executeDial(leadId: string, lead: Lead, viaPad = false) {
    setSelectedLeadId(leadId);
    const provider = viaPad ? padProvider : callingProvider;
    if (provider === "sim_basic" && !isMobileDialSurface()) {
      setSimHandoffLead(lead);
      return;
    }
    setDialing(leadId);
    try {
      const res = await api.calls.initiate(
        { leadId, callbackJobId: selectedCallbackJobId ?? undefined, mode: viaPad ? dialMode ?? undefined : undefined },
        callerId ?? undefined,
      );
      setActiveCallCtx({
        leadId: res.lead_id ?? leadId,
        name: res.lead_name ?? lead.name,
        phone: lead.phone,
        callLogId: res.call_log_id ?? null,
      });
      setActiveCallProvider(res.provider ?? provider);
      generatePreCallBrief(leadId);
      if (res.provider === "sim_basic") {
        const startedAt = new Date();
        if (!openNativeDialer(lead.phone)) {
          toast.error("This lead has no callable phone number.");
          return;
        }
        toast.success(`Opening phone dialer for ${lead.name || lead.phone}...`);
        window.setTimeout(() => primeSimWrapup(startedAt), 2500);
      } else {
        toast.success(`Calling ${lead.name || lead.phone}...`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Call failed");
    } finally {
      setDialing(null);
    }
  }

  async function executeManualDial(phone: string) {
    if (padProvider === "sim_basic" && !isMobileDialSurface()) {
      toast.info("Open Anril on your mobile to place SIM calls.");
      return;
    }
    setManualDialing(true);
    try {
      const res = await api.calls.initiate({ phone, mode: dialMode ?? undefined }, callerId ?? undefined);
      setActiveCallCtx({
        leadId: res.lead_id ?? null,
        name: res.lead_name ?? null,
        phone,
        callLogId: res.call_log_id ?? null,
      });
      setActiveCallProvider(res.provider ?? padProvider);
      setManualPhone("");
      if (res.provider === "sim_basic") {
        const startedAt = new Date();
        if (!openNativeDialer(phone)) {
          toast.error("Enter a valid phone number first.");
          return;
        }
        toast.success(`Opening phone dialer for ${phone}...`);
        window.setTimeout(() => primeSimWrapup(startedAt), 2500);
      } else {
        toast.success(`Calling ${phone}...`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Call failed");
    } finally {
      setManualDialing(false);
    }
  }

  // Accidental-dial countdown
  useEffect(() => {
    if (dialCountdown === null) return;
    if (dialCountdown === 0) {
      if (dialTarget) {
        if (dialTarget.leadId && dialTarget.lead) {
          executeDial(dialTarget.leadId, dialTarget.lead, dialTarget.viaPad);
        } else if (dialTarget.phone) {
          executeManualDial(dialTarget.phone);
        }
      }
      setDialCountdown(null);
      setDialTarget(null);
      return;
    }
    const timer = setTimeout(() => setDialCountdown(dialCountdown - 1), 1000);
    return () => clearTimeout(timer);
    // executeDial/executeManualDial intentionally omitted: the countdown fires
    // the dial for the dialTarget captured when it started.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dialCountdown, dialTarget]);

  // Live call status polling
  useEffect(() => {
    if (!activeCallCtx || !activeCallCtx.callLogId) {
      setCallStatus(null);
      setCallDuration(0);
      return;
    }
    if (activeCallProvider === "sim_basic") {
      return;
    }
    setCallStatus("ringing");
    setCallDuration(0);

    const pollInterval = setInterval(async () => {
      try {
        const log = await api.calls.getLog(activeCallCtx.callLogId!);
        if (log.status === "completed") {
          setCallStatus("ended");
          setShowWrapupModal(true);
          clearInterval(pollInterval);
        } else if (log.status === "no_answer") {
          // Nobody picked up: open the wrap-up pre-filled "Not picked" so the retry gets scheduled.
          setCallStatus("ended");
          setShowWrapupModal(true);
          clearInterval(pollInterval);
        } else if (log.status === "failed") {
          setCallStatus("ended");
          setActiveCallCtx(null);
          clearInterval(pollInterval);
          refreshQueueRef.current();
        } else if (log.status === "initiated") {
          setCallStatus((cur) => (cur === "ringing" ? "connected" : cur));
        }
      } catch (err) {
        console.error("Error polling call log:", err);
      }
    }, 3000);

    return () => clearInterval(pollInterval);
  }, [activeCallCtx, activeCallProvider, setActiveCallCtx]);

  // Call duration timer
  useEffect(() => {
    if (callStatus !== "connected") return;
    const timer = setInterval(() => setCallDuration((prev) => prev + 1), 1000);
    return () => clearInterval(timer);
  }, [callStatus]);

  // Wrap-up context: cloud pre-fill of tap 1 + retry suggestions (refetched once a SIM call gets its log id).
  const wrapLeadId = activeCallCtx?.leadId ?? null;
  const wrapLogId = activeCallCtx?.callLogId ?? null;
  useEffect(() => {
    if (!showWrapupModal) return;
    let cancelled = false;
    api.calls
      .wrapupContext({ leadId: wrapLeadId ?? undefined, callLogId: wrapLogId ?? undefined })
      .then((ctx) => {
        if (cancelled) return;
        setWrapupContext(ctx);
        setWrapupDraft((draft) => applyContext(draft, ctx));
      })
      .catch(() => {
        if (!cancelled) setWrapupContext(null);
      });
    return () => {
      cancelled = true;
    };
  }, [showWrapupModal, wrapLeadId, wrapLogId]);

  // Catalog for "Converted", loaded once the first time a wrap-up opens.
  useEffect(() => {
    if (!showWrapupModal || catalogLoaded.current) return;
    catalogLoaded.current = true;
    api.catalog.listItems().then(setCatalogItems).catch(() => {
      catalogLoaded.current = false;
    });
  }, [showWrapupModal]);

  // Fetch full details when a lead is selected
  useEffect(() => {
    if (!selectedLeadId) {
      setSelectedLead(null);
      setSelectedLeadNotes(null);
      setSelectedLeadMessages([]);
      setSelectedLeadCallLogs([]);
      setSelectedLeadBrief(null);
      setSelectedCallbackJobId(null);
      return;
    }
    setActiveProfileTab("overview");
    setSelectedLeadLoading(true);

    Promise.all([
      api.leads.get(selectedLeadId),
      fetchNotes(selectedLeadId).catch(() => ({ pinned: [], notes: [] })),
      api.leads.messages(selectedLeadId).catch(() => []),
      api.leads.callLogs(selectedLeadId).catch(() => []),
    ])
      .then(([leadData, notesData, messagesData, callLogsData]) => {
        setSelectedLead(leadData);
        setSelectedLeadNotes(notesData);
        setSelectedLeadMessages(messagesData);
        setSelectedLeadCallLogs(callLogsData);
      })
      .catch((err) => {
        toast.error("Failed to load lead profile");
        console.error(err);
      })
      .finally(() => setSelectedLeadLoading(false));
  }, [selectedLeadId]);

  // Auto-link a pending callback job for the selected lead
  useEffect(() => {
    if (selectedLeadId && todayCallbacks.length > 0) {
      const cb = todayCallbacks.find((c) => c.lead.id === selectedLeadId && c.status === "pending");
      setSelectedCallbackJobId(cb ? cb.id : null);
    } else {
      setSelectedCallbackJobId(null);
    }
  }, [selectedLeadId, todayCallbacks]);

  function composeNoteContent() {
    const title = quickNoteTitle.trim();
    const body = quickNoteContent.trim();
    return title ? `${title}\n\n${body}` : body;
  }

  function resetQuickNote() {
    setQuickNoteTitle("");
    setQuickNoteContent("");
    setQuickNoteTags([]);
    setQuickNotePinned(false);
    setCallbackDate("");
    setCallbackTime("");
    setShowCallbackPicker(false);
  }

  async function saveQuickNote(leadId: string) {
    const hasNote = quickNoteContent.trim().length > 0 || quickNoteTitle.trim().length > 0 || quickNoteTags.length > 0;
    const hasCallback = showCallbackPicker && !!callbackDate && !!callbackTime;
    if (!hasNote && !hasCallback) return;
    setQuickNoteSaving(true);
    try {
      if (hasNote) {
        await saveNote(leadId, composeNoteContent(), quickNotePinned, quickNoteTags);
      }
      if (hasCallback) {
        await createCallback(leadId, new Date(`${callbackDate}T${callbackTime}`).toISOString(), composeNoteContent());
      }
      resetQuickNote();
      toast.success(hasCallback ? "Callback scheduled" : "Note saved");
      fetchNotes(leadId).then(setSelectedLeadNotes).catch(() => {});
      loadCallbacks();
      if (hasCallback) refreshQueueRef.current();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save note");
    } finally {
      setQuickNoteSaving(false);
    }
  }

  function startImmediateSimLeadDial(leadId: string, lead: Lead, viaPad = false) {
    if (!openNativeDialer(lead.phone)) {
      toast.error("This lead has no callable phone number.");
      return;
    }

    const startedAt = new Date();
    setSelectedLeadId(leadId);
    setDialing(leadId);
    toast.success(`Opening phone dialer for ${lead.name || lead.phone}...`);

    // Synchronously set initial activeCallCtx and activeCallProvider so modal can render immediately
    setActiveCallCtx({
      leadId,
      name: lead.name,
      phone: lead.phone,
      callLogId: null,
    });
    setActiveCallProvider("sim_basic");

    // Synchronously schedule wrap-up modal to pre-open after 2.5 seconds
    window.setTimeout(() => primeSimWrapup(startedAt), 2500);

    void api.calls.initiate(
      { leadId, callbackJobId: selectedCallbackJobId ?? undefined, mode: viaPad ? dialMode ?? undefined : undefined },
      callerId ?? undefined,
    ).then((res) => {
      const provider = res.provider ?? "sim_basic";
      // Update activeCallCtx with actual callLogId from the server
      setActiveCallCtx({
        leadId: res.lead_id ?? leadId,
        name: res.lead_name ?? lead.name,
        phone: res.phone ?? lead.phone,
        callLogId: res.call_log_id ?? null,
      });
      setActiveCallProvider(provider);
      generatePreCallBrief(leadId);
    }).catch((err) => {
      if (err instanceof TypeError || (err instanceof Error && err.message.includes("Cannot reach server"))) {
        console.warn("Call initiated, but backend logging was interrupted by app backgrounding:", err);
      } else {
        toast.error(err instanceof Error ? err.message : "Call was opened, but Anril could not log it.");
      }
    }).finally(() => {
      setDialing(null);
    });
  }

  function startImmediateSimManualDial(phone: string) {
    if (!openNativeDialer(phone)) {
      toast.error("Enter a valid phone number first.");
      return;
    }

    const startedAt = new Date();
    setManualDialing(true);
    toast.success(`Opening phone dialer for ${phone}...`);

    // Synchronously set initial activeCallCtx and activeCallProvider so modal can render immediately
    setActiveCallCtx({
      leadId: null,
      name: null,
      phone,
      callLogId: null,
    });
    setActiveCallProvider("sim_basic");

    // Synchronously schedule wrap-up modal to pre-open after 2.5 seconds
    window.setTimeout(() => primeSimWrapup(startedAt), 2500);

    void api.calls.initiate({ phone, mode: dialMode ?? undefined }, callerId ?? undefined).then((res) => {
      const provider = res.provider ?? "sim_basic";
      // Update activeCallCtx with actual callLogId from the server
      setActiveCallCtx({
        leadId: res.lead_id ?? null,
        name: res.lead_name ?? null,
        phone: res.phone ?? phone,
        callLogId: res.call_log_id ?? null,
      });
      setActiveCallProvider(provider);
      setManualPhone("");
    }).catch((err) => {
      if (err instanceof TypeError || (err instanceof Error && err.message.includes("Cannot reach server"))) {
        console.warn("Call initiated, but backend logging was interrupted by app backgrounding:", err);
      } else {
        toast.error(err instanceof Error ? err.message : "Call was opened, but Anril could not log it.");
      }
    }).finally(() => {
      setManualDialing(false);
    });
  }

  async function handleRelease(leadId: string) {
    if (confirmRelease !== leadId) {
      setConfirmRelease(leadId);
      setTimeout(() => setConfirmRelease((cur) => (cur === leadId ? null : cur)), 3000);
      return;
    }
    setConfirmRelease(null);
    try {
      await api.leads.release(leadId);
      if (selectedLeadId === leadId) setSelectedLeadId(null);
      refreshQueueRef.current();
      toast.success("Lead released successfully");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to release lead");
    }
  }

  // viaPad: the call comes from the Manual Dial pad, so the Office number / My SIM choice applies.
  const dialWithGuard = useCallback((leadId: string, lead: Lead, viaPad = false) => {
    if (dialCountdown !== null) return;
    if ((viaPad ? padProvider : callingProvider) === "sim_basic" && isMobileDialSurface()) {
      startImmediateSimLeadDial(leadId, lead, viaPad);
      return;
    }
    setDialTarget({ leadId, lead, viaPad });
    setDialCountdown(3);
  }, [callingProvider, padProvider, dialCountdown]);

  const manualDialWithGuard = useCallback(() => {
    if (dialCountdown !== null) return;
    const phone = manualPhone.trim();
    if (!phone) return;
    if (padProvider === "sim_basic" && isMobileDialSurface()) {
      startImmediateSimManualDial(phone);
      return;
    }
    setDialTarget({ phone });
    setDialCountdown(3);
  }, [padProvider, dialCountdown, manualPhone]);

  const cancelDial = useCallback(() => {
    setDialCountdown(null);
    setDialTarget(null);
  }, []);

  async function handleCallNext() {
    setDialingNext(true);
    try {
      const nextLd = await api.calls.nextLead(callerId ?? undefined);
      const source = (nextLd as unknown as Record<string, unknown>)._source;
      if (source === "queue") {
        toast("Pool is empty — calling from your existing queue", { icon: "🔄" });
      } else {
        toast.success(`Claimed lead: ${nextLd.name || nextLd.phone}`);
      }
      setSelectedLeadId(nextLd.id);
      if (callingProvider === "sim_basic" && isMobileDialSurface()) {
        startImmediateSimLeadDial(nextLd.id, nextLd);
        return;
      }
      setDialTarget({ leadId: nextLd.id, lead: nextLd });
      setDialCountdown(3);
    } catch (err: unknown) {
      const errorObj = err as { status?: number; message?: string };
      if (errorObj?.status === 404) {
        toast.error("No leads available — pool and queue are both empty");
      } else {
        toast.error(err instanceof Error ? err.message : "Failed to fetch next lead");
      }
    } finally {
      setDialingNext(false);
    }
  }

  function resetWrapup() {
    setShowWrapupModal(false);
    setWrapupDraft(emptyDraft());
    setWrapupContext(null);
    setWrapupStartedAt("");
    setWrapupEndedAt("");
  }

  async function sendSimHandoffToMobile() {
    if (!simHandoffLead) return;
    setSimHandoffSending(true);
    try {
      const result = await api.calls.sendToMobile(simHandoffLead.id, callerId ?? undefined);
      if (!result.push_configured) {
        toast.info("Mobile push is not configured yet. Use the QR code or copy the number to open this lead on your phone.");
      } else if (result.subscription_count === 0) {
        toast.info("No mobile push subscription found. Open Anril on the phone, enable alerts, or use the QR code.");
      } else {
        toast.success("Sent to mobile");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to send to mobile");
    } finally {
      setSimHandoffSending(false);
    }
  }

  function openWrapupFromLog(log: CallLog) {
    setActiveCallCtx({
      leadId: log.lead_id,
      name: log.leads?.name || null,
      phone: log.leads?.phone || null,
      callLogId: log.id,
    });
    setActiveCallProvider(log.provider ?? "telecmi");
    if (log.provider === "sim_basic") {
      setWrapupStartedAt(log.manual_started_at ? toDateTimeInput(new Date(log.manual_started_at)) : toDateTimeInput(new Date(log.created_at)));
      setWrapupEndedAt(log.manual_ended_at ? toDateTimeInput(new Date(log.manual_ended_at)) : toDateTimeInput(new Date()));
    }
    setCallStatus("ended");
    setShowWrapupModal(true);
  }

  async function handleWrapupSubmit() {
    if (!activeCallCtx) return;
    const problem = draftError(wrapupDraft, new Date(), !!wrapupContext?.never_connected);
    if (problem) {
      toast.error(problem);
      return;
    }
    setWrapupSaving(true);
    try {
      let callLogId = activeCallCtx.callLogId;
      if (!callLogId) {
        toast.info("Logging call on server first...");
        try {
          const res = await api.calls.initiate(
            {
              leadId: activeCallCtx.leadId ?? undefined,
              phone: activeCallCtx.phone ?? undefined,
              callbackJobId: selectedCallbackJobId ?? undefined,
            },
            callerId ?? undefined,
          );
          callLogId = res.call_log_id;
          setActiveCallCtx({ ...activeCallCtx, callLogId: res.call_log_id });
        } catch (initErr) {
          throw new Error("Failed to create call log on server: " + (initErr instanceof Error ? initErr.message : String(initErr)));
        }
      }

      const isSim = activeCallProvider === "sim_basic";
      const saved = await api.calls.saveWrapup(callLogId, {
        ...draftToPayload(wrapupDraft),
        duration_seconds: isSim ? secondsBetween(wrapupStartedAt, wrapupEndedAt) : undefined,
        manual_started_at: isSim ? inputToIso(wrapupStartedAt) : undefined,
        manual_ended_at: isSim ? inputToIso(wrapupEndedAt) : undefined,
      });
      const notes = wrapupDraft.notes.trim();
      let noteFailed = false;
      if (notes && activeCallCtx.leadId) {
        // The wrap-up itself is already saved server-side -- a note failure here is a
        // separate, lesser problem. Don't reopen/keep open the modal or claim the whole
        // wrap-up failed; just tell the telecaller the note needs a manual re-save.
        try {
          await saveNote(activeCallCtx.leadId, notes, false, []);
        } catch {
          noteFailed = true;
        }
      }

      if (noteFailed) {
        toast.error("Wrap-up saved, but the note didn't save");
      } else {
        toast.success(
          saved.next_action_at
            ? `Wrap-up saved · reminder ${formatIstWhen(new Date(saved.next_action_at), new Date())}`
            : "Wrap-up saved",
        );
      }
      resetWrapup();
      setActiveCallProvider("telecmi");
      setActiveCallCtx(null);
      refreshQueueRef.current();
      loadCallbacks();
      loadPendingWrapups();
    } catch (err: unknown) {
      const errorObj = err as { status?: number; message?: string };
      if (errorObj?.status === 422) {
        toast.error("The app was updated — please refresh the page and save again.");
      } else {
        toast.error(err instanceof Error ? err.message : "Failed to submit wrap-up");
      }
    } finally {
      setWrapupSaving(false);
    }
  }

  // Props bag for LeadDetailPanel. selectedLead is cast: the panel itself
  // renders a loader when it's null, and pages only mount it once a lead is chosen.
  const leadDetailProps: LeadDetailPanelProps = {
    selectedLead: selectedLead as Lead,
    selectedLeadNotes,
    selectedLeadMessages,
    selectedLeadCallLogs,
    selectedLeadBrief,
    briefLoading,
    generatePreCallBrief,
    selectedLeadLoading,
    activeProfileTab,
    setActiveProfileTab,
    activeCallCtx,
    callStatus,
    callDuration,
    quickNoteTitle,
    setQuickNoteTitle,
    quickNoteContent,
    setQuickNoteContent,
    quickNoteSaving,
    saveQuickNote,
    quickNoteTags,
    setQuickNoteTags,
    quickNotePinned,
    setQuickNotePinned,
    showCallbackPicker,
    setShowCallbackPicker,
    callbackDate,
    setCallbackDate,
    callbackTime,
    setCallbackTime,
    confirmRelease,
    handleRelease,
    dialWithGuard,
    dialing,
    telecallingConfig,
    scriptExpanded,
    setScriptExpanded,
    setHistoryLead: () => {},
  };

  return {
    // selection
    selectedLeadId,
    setSelectedLeadId,
    selectedLead,
    // queue helpers
    todayCallbacks,
    // manual dial
    manualPhone,
    setManualPhone,
    manualDialing,
    manualDialWithGuard,
    // call next
    dialingNext,
    handleCallNext,
    // dialing
    dialing,
    dialWithGuard,
    // active call
    activeCallCtx,
    simHandoffLead,
    setSimHandoffLead,
    simHandoffSending,
    sendSimHandoffToMobile,
    // lead detail panel
    leadDetailProps,
    // modal state (CockpitModals)
    callingProvider,
    dialMode,
    setDialMode,
    officeReady,
    activeCallProvider,
    dialCountdown,
    dialTarget,
    cancelDial,
    showWrapupModal,
    wrapupDraft,
    setWrapupDraft,
    wrapupContext,
    catalogItems,
    wrapupStartedAt,
    setWrapupStartedAt,
    wrapupEndedAt,
    setWrapupEndedAt,
    wrapupSaving,
    handleWrapupSubmit,
    pendingWrapups,
    openWrapupFromLog,
    blockingWrapups,
  };
}

export type CallingCockpit = ReturnType<typeof useCallingCockpit>;
