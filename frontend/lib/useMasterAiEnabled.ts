"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/** Account-wide AI Auto-Reply switch (Settings → Auto-Reply). Assumed on until the read succeeds. */
export function useMasterAiEnabled(): boolean {
  const [enabled, setEnabled] = useState(true);
  useEffect(() => {
    let live = true;
    api.settings.getAiAutoReply().then((r) => live && setEnabled(r.enabled)).catch(() => {});
    return () => { live = false; };
  }, []);
  return enabled;
}
