import { useEffect, useRef, useState } from "react";
import { api, type CallLog, type DialCheck, type DialCheckRow } from "@/lib/api";

export type { DialCheck, DialCheckRow };

export function stateTone(state: DialCheckRow["state"]): "ok" | "bad" | "warn" | "muted" {
  if (state === "ok") return "ok";
  if (state === "blocked") return "bad";
  if (state === "warn") return "warn";
  return "muted";
}

export function callingFromLabel(v: "office" | "sim"): string {
  return v === "sim" ? "Your phone (SIM)" : "Office number";
}

/** Worth asking the server: 10+ digits and no letters. */
export function worthChecking(text: string): boolean {
  return !/[a-z]/i.test(text) && text.replace(/\D/g, "").length >= 10;
}

/** What a stored check answers for: the typed text, who is calling, and which call round it is. */
export function checkKey(phone: string, callerId: string | null | undefined, round: number): string {
  return `${phone}|${callerId ?? ""}|${round}`;
}

export interface DialCheckState {
  check: DialCheck | null;
  loading: boolean;
  /** Plain-words reason when the server could not check (shown in place of the checks). */
  error: string | null;
  today: CallLog[];
}

/** Checks for the number typed on the Manual Dial pad, plus the calls this caller made today. */
export function useDialCheck(phone: string, callerId?: string | null, dialing = false): DialCheckState {
  const [result, setResult] = useState<{ key: string; check: DialCheck | null; error: string | null } | null>(null);
  const [today, setToday] = useState<CallLog[]>([]);
  const wasDialing = useRef(false);
  const [round, setRound] = useState(0);
  const key = checkKey(phone, callerId, round);

  useEffect(() => {
    if (!worthChecking(phone)) return;
    let stale = false;
    const t = setTimeout(() => {
      api.calls
        .dialCheck(phone, callerId ?? undefined)
        .then((check) => {
          if (!stale) setResult({ key, check, error: null });
        })
        .catch((err: unknown) => {
          if (!stale) setResult({ key, check: null, error: err instanceof Error ? err.message : "Couldn't check this number right now." });
        });
    }, 300);
    return () => {
      stale = true;
      clearTimeout(t);
    };
  }, [phone, callerId, key]);

  useEffect(() => {
    let stale = false;
    const justEnded = wasDialing.current && !dialing;
    wasDialing.current = dialing;
    if (justEnded) setRound((r) => r + 1);
    if (dialing && !justEnded) return;
    api.calls
      .recent(50, callerId ?? undefined, { today: true })
      .then((rows) => {
        if (!stale) setToday(rows);
      })
      .catch(() => {});
    return () => {
      stale = true;
    };
  }, [callerId, dialing]);

  const current = worthChecking(phone) && result?.key === key ? result : null;
  return {
    check: current?.check ?? null,
    error: current?.error ?? null,
    loading: worthChecking(phone) && !current,
    today,
  };
}
