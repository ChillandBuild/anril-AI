"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePolling } from "@/hooks/usePolling";

export interface CallIqData<T> {
  data: T | null;
  err: string | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Loads one Call IQ report. `key` changes (a new period) start a fresh load; `refreshMs` reloads quietly in
 * the background (the old numbers stay on screen), and only while the tab is visible.
 */
export function useCallIqData<T>(load: () => Promise<T>, key: string, enabled = true, refreshMs?: number): CallIqData<T> {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(enabled);
  const loadRef = useRef(load);
  loadRef.current = load;
  const keyRef = useRef(key);
  keyRef.current = key;

  const run = useCallback((quiet: boolean) => {
    const forKey = keyRef.current;
    if (!quiet) setLoading(true);
    loadRef.current()
      .then((d) => {
        if (keyRef.current !== forKey) return;
        setData(d);
        setErr(null);
      })
      .catch((e: unknown) => {
        if (keyRef.current !== forKey) return;
        // A failed background refresh keeps the numbers already shown.
        if (!quiet) setErr(e instanceof Error ? e.message : "This did not load. Try again.");
      })
      .finally(() => {
        if (keyRef.current === forKey) setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (!enabled) return;
    setData(null);
    setErr(null);
    run(false);
  }, [key, enabled, run]);

  usePolling(() => run(true), refreshMs ?? 60_000, enabled && !!refreshMs);

  const reload = useCallback(() => run(false), [run]);
  return { data, err, loading, reload };
}
