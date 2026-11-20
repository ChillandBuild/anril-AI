"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import type { MetaBusinessAssets, MetaBusinessLoginState } from "./channels";
import { MetaSignupCoordinator, buildMetaLoginOptions } from "./metaSignupMode";
import type { MetaSignupMode, ReadyMetaSignup } from "./metaSignupMode";

// Not secrets — safe to expose client-side. Env var lets prod/staging override.
export const META_APP_ID = process.env.NEXT_PUBLIC_META_APP_ID || "2225044871604460";
const META_UNIFIED_CONFIG_ID = process.env.NEXT_PUBLIC_META_UNIFIED_CONFIG_ID || "2026693308738446";
// Meta makes every asset listed in a Login configuration mandatory, so a customer
// with no Page or ad account cannot get through the unified window at all. This
// WhatsApp-only configuration asks for the WABA and nothing else, and doubles as the
// coexistence configuration — that flow is switched on by the extras sent at login
// time, not by the configuration. It last completed a real coexistence signup on
// 2026-08-10 (tenant Astro Tamil - Co).
const META_WHATSAPP_ONLY_CONFIG_ID =
  process.env.NEXT_PUBLIC_META_WHATSAPP_ONLY_CONFIG_ID || "1063294086656120";

declare global {
  interface Window {
    FB?: {
      init: (params: { appId: string; xfbml?: boolean; version: string }) => void;
      login: (
        callback: (response: { authResponse?: { code?: string } }) => void,
        options: {
          config_id: string;
          response_type: string;
          override_default_response_type: boolean;
          extras?: { setup?: Record<string, never>; featureType?: string; sessionInfoVersion?: string };
        }
      ) => void;
    };
    fbAsyncInit?: () => void;
  }
}

let fbSdkPromise: Promise<void> | null = null;
export function loadFacebookSdk(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (window.FB) return Promise.resolve();
  if (fbSdkPromise) return fbSdkPromise;
  fbSdkPromise = new Promise((resolve) => {
    window.fbAsyncInit = () => {
      window.FB!.init({ appId: META_APP_ID, xfbml: false, version: "v25.0" });
      resolve();
    };
    const script = document.createElement("script");
    script.src = "https://connect.facebook.net/en_US/sdk.js";
    script.async = true;
    script.defer = true;
    document.body.appendChild(script);
  });
  return fbSdkPromise;
}

/**
 * Drives Meta's Embedded Signup v4: opens the Meta window, exchanges the one-time
 * code server-side, then lets the tenant pick which granted assets to connect.
 */
export function useMetaSignup({
  canManage,
  onConnected,
}: {
  canManage: boolean;
  onConnected: () => void | Promise<void>;
}) {
  const [state, setState] = useState<MetaBusinessLoginState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [assets, setAssets] = useState<MetaBusinessAssets | null>(null);
  const [selectedPageId, setSelectedPageId] = useState("");
  const [selectedAdAccountId, setSelectedAdAccountId] = useState("");
  const [selectedCatalogId, setSelectedCatalogId] = useState("");
  const [activeMode, setActiveMode] = useState<MetaSignupMode | null>(null);
  const coordinatorRef = useRef(new MetaSignupCoordinator());
  // The requested mode has to outlive `activeMode`, which clears the moment the Meta
  // window closes — `finish` still needs to know whether to skip the asset picker.
  const requestedModeRef = useRef<MetaSignupMode | null>(null);

  const submitSelection = useCallback(async (
    sessionId: string,
    pageId: string | null,
    adAccountId: string | null,
    catalogId: string | null = null,
  ) => {
    const auth = await getAuthHeaders();
    const res = await fetch(`${API_URL}/api/v1/settings/meta/unified-signup/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...auth },
      body: JSON.stringify({ session_id: sessionId, page_id: pageId, ad_account_id: adAccountId, catalog_id: catalogId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Connecting Meta Business failed");
  }, []);

  const finish = useCallback(async ({ code, session }: ReadyMetaSignup) => {
    if (!canManage) return;
    setActiveMode(null);
    setState("connecting");
    setError(null);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/meta/unified-signup/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({
          code,
          waba_id: session.waba_id,
          phone_number_id: session.phone_number_id,
          business_id: session.business_id,
          is_coexistence: session.is_coexistence ?? false,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Meta could not list the assets you granted");
      const granted = data as MetaBusinessAssets;

      // The WhatsApp-only configuration grants no Page and no ad account, so there is
      // nothing to choose — an empty picker would only add a dead click.
      if (requestedModeRef.current !== "standard") {
        setState("finishing");
        await submitSelection(granted.session_id, null, null);
        setAssets(null);
        setState("success");
        await onConnected();
        return;
      }

      setAssets(granted);
      setSelectedPageId(granted.pages.length === 1 ? granted.pages[0].id : "");
      setSelectedAdAccountId("");
      setSelectedCatalogId(granted.catalogs?.length === 1 ? granted.catalogs[0].id : "");
      setState("selecting");
      setActiveMode(null);
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : "Connecting Meta Business failed");
      setActiveMode(null);
    }
  }, [canManage, submitSelection, onConnected]);

  useEffect(() => {
    function handleUnifiedMessage(event: MessageEvent) {
      if (event.origin !== "https://www.facebook.com" && event.origin !== "https://web.facebook.com") return;
      if (!event.source || typeof event.source !== "object") return;
      try {
        const ready = coordinatorRef.current.receiveMessage(event.data as unknown, event.source);
        if (ready) void finish(ready);
      } catch (err) {
        setState("error");
        setError(err instanceof Error ? err.message : "Meta returned the wrong signup flow");
        setActiveMode(null);
      }
    }
    window.addEventListener("message", handleUnifiedMessage);
    return () => window.removeEventListener("message", handleUnifiedMessage);
  }, [finish]);

  const start = useCallback(async (mode: MetaSignupMode) => {
    if (!canManage) return;
    const attemptId = coordinatorRef.current.begin(mode);
    if (attemptId === null) return;
    setState("connecting");
    setError(null);
    setActiveMode(mode);
    requestedModeRef.current = mode;
    try {
      await loadFacebookSdk();
      window.FB?.login(
        (response) => {
          if (!coordinatorRef.current.isActive(attemptId)) return;
          const code = response?.authResponse?.code;
          if (!code) {
            coordinatorRef.current.cancel(attemptId);
            setState("idle");
            setActiveMode(null);
            return;
          }
          const ready = coordinatorRef.current.receiveCode(attemptId, code);
          if (ready) void finish(ready);
        },
        buildMetaLoginOptions(
          mode === "standard" ? META_UNIFIED_CONFIG_ID : META_WHATSAPP_ONLY_CONFIG_ID,
          mode
        )
      );
    } catch (err) {
      coordinatorRef.current.cancel(attemptId);
      setState("error");
      setError(err instanceof Error ? err.message : "Could not open Meta signup");
      setActiveMode(null);
    }
  }, [canManage, finish]);

  const startStandard = useCallback(() => start("standard"), [start]);
  const startWhatsAppOnly = useCallback(() => start("whatsapp_only"), [start]);
  const startCoexistence = useCallback(() => start("coexistence"), [start]);

  const complete = useCallback(async () => {
    // No Page is a valid outcome — WhatsApp connects on its own, Messenger and
    // Instagram simply stay unconnected.
    if (!canManage || !assets) return;
    setState("finishing");
    setError(null);
    try {
      await submitSelection(assets.session_id, selectedPageId || null, selectedAdAccountId || null, selectedCatalogId || null);
      setAssets(null);
      setState("success");
      await onConnected();
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : "Connecting Meta Business failed");
    }
  }, [canManage, assets, selectedPageId, selectedAdAccountId, selectedCatalogId, submitSelection, onConnected]);

  const dismissAssets = useCallback(() => {
    setAssets(null);
    setState("idle");
    setError(null);
    setActiveMode(null);
  }, []);

  const isBusy = state === "connecting" || state === "finishing";

  return {
    state,
    error,
    assets,
    selectedPageId,
    selectedAdAccountId,
    selectedCatalogId,
    activeMode,
    setSelectedPageId,
    setSelectedAdAccountId,
    setSelectedCatalogId,
    startStandard,
    startWhatsAppOnly,
    startCoexistence,
    complete,
    dismissAssets,
    isBusy,
  };
}
