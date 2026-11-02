"use client";
import { useEffect, useState } from "react";
import { AnrilMark } from "@/components/logo";
import { cn } from "@/lib/utils";

interface AiraLoaderProps {
  showRetryAfterMs?: number;
  onRetry?: () => void;
  /**
   * Render in place (inside the page content or a section) instead of as a
   * full-screen overlay, so the sidebar and header stay visible while a page
   * or panel loads its first data.
   */
  inline?: boolean;
  /** Extra classes for the inline container, e.g. a min height. */
  className?: string;
}

export function AiraLoader({ showRetryAfterMs, onRetry, inline = false, className }: AiraLoaderProps) {
  const [showRetry, setShowRetry] = useState(false);

  useEffect(() => {
    if (!showRetryAfterMs) return;
    const t = setTimeout(() => {
      setShowRetry(true);
    }, showRetryAfterMs);
    return () => clearTimeout(t);
  }, [showRetryAfterMs]);

  return (
    <div
      role="status"
      aria-live="polite"
      className={inline
        ? cn("flex w-full flex-col items-center justify-center p-4 text-center", className ?? "min-h-[60vh]")
        : "fixed inset-0 z-dialog flex flex-col items-center justify-center bg-[#f1f5f9] p-4 text-center"}
    >
      <div className={cn("flex flex-col items-center", inline ? "gap-3" : "gap-4")}>
        {!showRetry && (
          <AnrilMark
            width={inline ? 32 : 44}
            height={inline ? 32 : 44}
            className="aira-loader-mark text-[#0A1528]"
            aria-label="Loading"
          />
        )}
        {!inline && (
          <span className="text-xs font-medium tracking-widest text-[#475569] uppercase">
            Anril
          </span>
        )}
        {showRetry && (
          <div className="mt-4 max-w-sm animate-in fade-in duration-300">
            <p className="font-body text-sm text-[#475569] mb-3">
              Couldn&apos;t reach the server. The backend may be waking up — this can take 30–60 seconds.
            </p>
            {onRetry && (
              <button
                onClick={onRetry}
                className="btn-primary text-sm px-6 py-2"
              >
                Retry
              </button>
            )}
          </div>
        )}
      </div>

      <style>{`
        /* The mark assembles: navy squares pop in, the teal square lands last, then it resets. */
        .aira-loader-mark rect {
          transform-box: fill-box;
          transform-origin: center;
          transform: scale(0);
          opacity: 0;
          animation: aira-loader-pop 1.8s cubic-bezier(0.34, 1.56, 0.64, 1) infinite;
        }
        .aira-loader-mark rect:nth-of-type(3) { animation-delay: 0.12s; }
        .aira-loader-mark rect:nth-of-type(4) { animation-delay: 0.24s; }
        .aira-loader-mark rect:nth-of-type(2) { animation-delay: 0.42s; }
        @keyframes aira-loader-pop {
          0% { transform: scale(0); opacity: 0; }
          18%, 70% { transform: scale(1); opacity: 1; }
          88%, 100% { transform: scale(0); opacity: 0; }
        }
        @media (prefers-reduced-motion: reduce) {
          .aira-loader-mark rect {
            transform: none;
            animation: aira-loader-fade 1.6s ease-in-out infinite;
          }
          @keyframes aira-loader-fade {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
          }
        }
      `}</style>
    </div>
  );
}
