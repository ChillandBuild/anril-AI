"use client";
import { useEffect, useState } from "react";
import useSWR, { type SWRConfiguration } from "swr";
import { api, type AdPerformanceSummary, type HomeLayout, type HomeToday, type TelecallingAnalytics } from "@/lib/api";
import { firstSetupApi, type FirstSetupProgress } from "@/lib/firstSetupApi";
import { homeIsReady } from "./homeReady";

/**
 * Home's data calls, each under one SWR name. The gate (useHomeGate) and the block that draws the data ask
 * under the same name, so there is one network call and the gate can see when it has finished.
 */

const liveOpts: SWRConfiguration = {
  revalidateOnFocus: true,
  revalidateOnReconnect: true,
  dedupingInterval: 5_000,
  errorRetryCount: 2,
  shouldRetryOnError: (error: unknown) => {
    const status = (error as { status?: number } | undefined)?.status;
    return !status || ![401, 403, 404].includes(status);
  },
};

// These three cards asked once when Home opened and never again. Keep that: no refetch on focus, no retry.
const onceOpts: SWRConfiguration = {
  revalidateOnFocus: false,
  revalidateOnReconnect: false,
  shouldRetryOnError: false,
  dedupingInterval: 5_000,
};

export function useHomeToday(enabled = true) {
  return useSWR<HomeToday>(enabled ? "home/today" : null, () => api.home.today(), { ...liveOpts, refreshInterval: 120_000 });
}

export function useHomeLayout(enabled = true) {
  return useSWR<HomeLayout>(enabled ? "home/layout" : null, () => api.home.layout(), liveOpts);
}

/** The wizard writes its saved progress under this name, so Home's "Finish setup" card is right on the way back. */
export const SETUP_PROGRESS_KEY = "home/setup-progress";

export function useSetupProgress(enabled = true) {
  return useSWR<FirstSetupProgress>(enabled ? SETUP_PROGRESS_KEY : null, () => firstSetupApi.progress(), onceOpts);
}

export function useAdSpend(enabled = true) {
  return useSWR<AdPerformanceSummary>(enabled ? "home/ad-spend" : null, () => api.analytics.adPerformance(), onceOpts);
}

export function useTeamCalls(enabled = true) {
  return useSWR<TelecallingAnalytics>(enabled ? "home/team-calls" : null, () => api.analytics.telecalling(), onceOpts);
}

/** A call has finished when it has an answer or an error. */
function done(call: { data?: unknown; error?: unknown }): boolean {
  return call.data !== undefined || call.error !== undefined;
}

const TICK_MS = 250;

/**
 * Holds Home behind the loader until its data is in, so the page opens whole instead of filling in piece by
 * piece. The rule for "in" is homeIsReady. Once open it stays open, so a later refresh never brings the loader back.
 * `enabled` is false for people who never see Home (they are being sent elsewhere): nothing is fetched for them.
 */
export function useHomeGate(enabled: boolean, telecalling: boolean): boolean {
  const today = useHomeToday(enabled);
  const layout = useHomeLayout(enabled);
  const setup = useSetupProgress(enabled);
  const adSpend = useAdSpend(enabled);
  const teamCalls = useTeamCalls(enabled && telecalling);

  const [waitedMs, setWaitedMs] = useState(0);
  const [open, setOpen] = useState(false);

  const ready =
    enabled &&
    homeIsReady(
      {
        today: done(today),
        layout: done(layout),
        setup: done(setup),
        adSpend: done(adSpend),
        teamCalls: !telecalling || done(teamCalls),
      },
      waitedMs,
    );
  // Latch during render (React re-renders at once): no frame is painted with the loader after Home is ready.
  if (ready && !open) setOpen(true);

  useEffect(() => {
    if (!enabled || open) return;
    const started = Date.now();
    const id = setInterval(() => setWaitedMs(Date.now() - started), TICK_MS);
    return () => clearInterval(id);
  }, [enabled, open]);

  return open || ready;
}
