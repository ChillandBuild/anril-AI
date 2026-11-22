"use client";

import { useEffect, useRef, useState } from "react";
import { Camera, Loader2, ScanLine, X } from "lucide-react";
import { toast } from "sonner";
import { api, type ScanResult } from "@/lib/api";
import { code128Bars } from "@/lib/code128";
import { cn } from "@/lib/utils";

/* Scan to add: a USB scanner types the code and presses Enter into this box; on a phone, the camera
 * button reads it (browsers with the built-in barcode reader). Typing the code works everywhere. */

type Detector = { detect: (src: CanvasImageSource) => Promise<{ rawValue: string }[]> };
type DetectorCtor = new (opts: { formats: string[] }) => Detector;

export function ScanBox({ onFound, placeholder = "Scan or type a barcode", className, autoFocus }: {
  onFound: (item: ScanResult) => void; placeholder?: string; className?: string; autoFocus?: boolean;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [camera, setCamera] = useState(false);
  const [canCamera, setCanCamera] = useState(false);

  useEffect(() => {
    setCanCamera(typeof window !== "undefined" && "BarcodeDetector" in window && !!navigator.mediaDevices?.getUserMedia);
  }, []);

  async function find(value: string) {
    const v = value.trim();
    if (!v) return;
    setBusy(true);
    try {
      onFound(await api.catalog.scan(v));
      setCode("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "No item has this barcode.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <label className="relative flex-1">
        <ScanLine size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
        <input value={code} onChange={(e) => setCode(e.target.value)} autoFocus={autoFocus} placeholder={placeholder}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); find(code); } }} aria-label="Barcode"
          className="h-10 w-full rounded-xl border border-border bg-white pl-9 pr-8 font-mono text-sm uppercase outline-none focus:border-primary" />
        {busy && <Loader2 size={14} className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-ink-muted" />}
      </label>
      {canCamera && (
        <button type="button" onClick={() => setCamera(true)} aria-label="Scan with the camera"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border bg-white text-ink hover:bg-surface-low">
          <Camera size={16} />
        </button>
      )}
      {camera && <CameraScan onClose={() => setCamera(false)} onCode={(v) => { setCamera(false); find(v); }} />}
    </div>
  );
}

function CameraScan({ onClose, onCode }: { onClose: () => void; onCode: (code: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const report = useRef(onCode);
  report.current = onCode;

  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;
    let done = false;
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        if (!video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        const Ctor = (window as unknown as { BarcodeDetector: DetectorCtor }).BarcodeDetector;
        const detector = new Ctor({ formats: ["code_128", "ean_13", "ean_8", "upc_a", "upc_e"] });
        timer = setInterval(async () => {
          if (done || !video.current) return;
          try {
            const found = await detector.detect(video.current);
            if (found[0]?.rawValue && !done) {
              done = true;
              report.current(found[0].rawValue);
            }
          } catch { /* next frame */ }
        }, 300);
      } catch {
        setProblem("Couldn't open the camera. Allow camera access, or type the code.");
      }
    })();
    return () => {
      done = true;
      if (timer) clearInterval(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="w-full max-w-md overflow-hidden rounded-2xl bg-white" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <p className="font-display font-bold text-ink">Point the camera at the barcode</p>
          <button type="button" onClick={onClose} aria-label="Close" className="text-ink-muted hover:text-ink"><X size={18} /></button>
        </div>
        {problem ? <p className="px-4 py-8 text-center text-sm text-danger">{problem}</p>
          : <video ref={video} muted playsInline className="aspect-[4/3] w-full bg-black object-cover" />}
      </div>
    </div>
  );
}

/** One Code 128 barcode as SVG (scales to its box; bars stay crisp in print). */
export function Barcode({ code, className }: { code: string; className?: string }) {
  let shape: ReturnType<typeof code128Bars>;
  try {
    shape = code128Bars(code);
  } catch {
    return null;
  }
  const quiet = 10;
  const width = shape.width + quiet * 2;
  return (
    <svg viewBox={`0 0 ${width} 40`} preserveAspectRatio="none" className={className} role="img" aria-label={`Barcode ${code}`}>
      <rect width={width} height={40} fill="#fff" />
      {shape.bars.map((b) => <rect key={b.x} x={b.x + quiet} width={b.w} height={40} fill="#000" />)}
    </svg>
  );
}
