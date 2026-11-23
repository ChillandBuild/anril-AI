"use client";
import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { TILE_META } from "./tiles";
import type { ChannelState, TileId, TileStatus } from "./tiles";

export type TileMenuItem = {
  label: string;
  hint?: string;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
};

const PILL: Record<ChannelState, string> = {
  receiving: "bg-green-100 text-green-800",
  synced: "bg-green-100 text-green-800",
  waiting: "bg-amber-100 text-amber-800",
  attention: "bg-rose-100 text-rose-700",
  off: "bg-slate-100 text-slate-600",
};

export function StatePill({ state, label }: { state: ChannelState; label: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-label text-xs font-bold", PILL[state])}>
      <span className="h-[7px] w-[7px] rounded-full bg-current" />
      {label}
    </span>
  );
}

function TileMenu({ name, items }: { name: string; items: TileMenuItem[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`More ${name} options`}
        className="inline-flex h-8 w-9 items-center justify-center rounded-[10px] border border-border bg-white font-label text-[15px] font-extrabold text-ink transition-colors hover:border-primary/40 hover:text-primary"
      >
        ⋯
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-10 z-10 w-60 rounded-xl border border-border bg-white p-1.5 shadow-card">
          {items.map(item => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={cn(
                "block w-full rounded-lg px-3 py-2.5 text-left font-body text-[13px] transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50",
                item.danger ? "text-red-700" : "text-ink",
              )}
            >
              {item.label}
              {item.hint && <span className="mt-0.5 block text-xs text-ink-muted">{item.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ChannelTile({
  id,
  account,
  status,
  bottom,
  connected,
  busy = false,
  canManage,
  menu,
  onManage,
  onConnect,
}: {
  id: TileId;
  account: string;
  status: TileStatus;
  bottom: string;
  connected: boolean;
  busy?: boolean;
  canManage: boolean;
  menu: TileMenuItem[];
  onManage: () => void;
  onConnect: () => void;
}) {
  const meta = TILE_META[id];
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-white p-4 shadow-card">
      <div className="flex items-center gap-3">
        <span aria-hidden="true" className={cn("flex h-10 w-10 flex-none items-center justify-center rounded-xl font-label text-sm font-extrabold", meta.badge)}>
          {meta.initials}
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-display font-extrabold text-ink">{meta.name}</div>
          <div className="truncate font-body text-xs text-ink-secondary" title={account}>{account}</div>
        </div>
        {canManage && menu.length > 0 && <TileMenu name={meta.name} items={menu} />}
      </div>
      <div className="flex items-center justify-between gap-2">
        <StatePill state={status.state} label={status.label} />
        {connected ? (
          <button type="button" onClick={onManage} aria-label={`Manage ${meta.name}`} className="inline-flex items-center rounded-[10px] border border-border bg-white px-3.5 py-2 font-label text-[13px] font-bold text-ink transition-colors hover:border-primary/40 hover:text-primary">
            Manage
          </button>
        ) : (
          <button type="button" onClick={onConnect} disabled={!canManage || busy} aria-label={`Connect ${meta.name}`} className="btn-primary !rounded-[10px] !px-3.5">
            {busy && <Loader2 size={13} className="animate-spin" />}
            {busy ? "Opening…" : "Connect"}
          </button>
        )}
      </div>
      <div className="font-body text-xs text-ink-secondary">{bottom}</div>
    </div>
  );
}
