"use client";
import { useEffect, useRef, useState } from "react";
import { Mic, Play, Loader2 } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * A WhatsApp voice note in the chat: "🎤 Voice note" with Play, and under it what the AI heard
 * (the transcript it replied to). The sound is fetched from WhatsApp only when Play is pressed.
 */
export function VoiceNote({
  leadId,
  messageId,
  heard,
  playable,
  onDark,
}: {
  leadId: string;
  messageId: string;
  heard: string;
  playable: boolean;
  onDark: boolean;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => () => { if (src) URL.revokeObjectURL(src); }, [src]);
  useEffect(() => { if (src) audioRef.current?.play().catch(() => {}); }, [src]);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/v1/leads/${leadId}/messages/${messageId}/audio`, { headers: await getAuthHeaders() });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(typeof body?.detail === "string" ? body.detail : "Couldn't play this voice note.");
      }
      setSrc(URL.createObjectURL(await res.blob()));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't play this voice note.");
    } finally {
      setBusy(false);
    }
  }

  const muted = onDark ? "text-white/75" : "text-[#64748b]";
  return (
    <div className="min-w-[200px] max-w-[300px]">
      <div className="flex items-center gap-2">
        <Mic size={15} className={onDark ? "text-white/85" : "text-primary"} aria-hidden />
        <span className="font-label text-sm font-semibold">Voice note</span>
        {playable && !src && (
          <button
            type="button"
            onClick={load}
            disabled={busy}
            className={cn(
              "ml-auto inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold transition disabled:opacity-60",
              onDark ? "bg-white/15 text-white hover:bg-white/25" : "bg-primary/10 text-primary hover:bg-primary/15",
            )}
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} fill="currentColor" />}
            {busy ? "Getting it…" : "Play"}
          </button>
        )}
      </div>
      {src && <audio ref={audioRef} src={src} controls className="mt-2 h-9 w-full" />}
      {error && <p className={cn("mt-1 text-xs", onDark ? "text-white/80" : "text-warning")}>{error}</p>}
      {heard && (
        <p className={cn("mt-1.5 whitespace-pre-wrap text-xs", muted)}>
          <span className="font-semibold">AI heard:</span> “{heard}”
        </p>
      )}
    </div>
  );
}
