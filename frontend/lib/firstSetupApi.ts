import { apiFetch } from "@/lib/api";

/** v9.2 #27: first setup progress, and the public "forgot password" request. */

export type FirstSetupStep = "business" | "items" | "hours" | "alerts" | "connect" | "ai";

export const FIRST_SETUP_STEPS: FirstSetupStep[] = ["business", "items", "hours", "alerts", "connect", "ai"];

export type FirstSetupProgress = { step: FirstSetupStep; done_steps: FirstSetupStep[] };

export const firstSetupApi = {
  progress: () => apiFetch<FirstSetupProgress>("/api/v1/first-setup/progress"),
  saveProgress: (body: FirstSetupProgress) =>
    apiFetch<FirstSetupProgress>("/api/v1/first-setup/progress", { method: "PUT", body: JSON.stringify(body) }),
};

/** Public: works without signing in. The reply is the same whoever is typed. */
export function requestPasswordHelp(body: { identifier: string; business_name: string; note: string }) {
  return apiFetch<{ message: string }>("/api/v1/password-help/request", { method: "POST", body: JSON.stringify(body) });
}

/** The AI agent's master switch: the same setting Settings > Auto-reply changes. */
export function setAiAgentOn(on: boolean) {
  return apiFetch<unknown>("/api/v1/settings/", {
    method: "PATCH",
    body: JSON.stringify({ updates: { ai_auto_reply_enabled: on ? "true" : "false" } }),
  });
}
