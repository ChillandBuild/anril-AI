"use client";
import { useEffect, useState } from "react";
import { api, type Winner as WinnerEntry } from "@/lib/api";

type Winner = WinnerEntry | null;

type WinnersData = { daily: Winner; monthly: Winner };

const FORMULA = "Winner points = 70% average call score + 30% calls made (compared with the busiest telecaller).";

function Initials({ name }: { name: string }) {
  const parts = name.trim().split(" ");
  const letters =
    parts.length >= 2
      ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
      : name.slice(0, 2).toUpperCase();
  return <span className="text-white font-bold text-lg leading-none">{letters}</span>;
}

function WinnerCard({
  type,
  winner,
  loading,
}: {
  type: "daily" | "monthly";
  winner: Winner;
  loading: boolean;
}) {
  const isDaily = type === "daily";

  const gradientClass = isDaily
    ? "from-amber-400 via-orange-400 to-rose-400"
    : "from-primary-500 via-primary-500 to-primary";

  const avatarClass = isDaily
    ? "bg-white/25 ring-2 ring-white/40"
    : "bg-white/25 ring-2 ring-white/40";

  const shimmerClass = isDaily ? "bg-amber-300/40" : "bg-primary-400/40";

  const label = isDaily ? "⚡ Daily Winner" : "👑 Monthly Champion";
  const emptyMsg = isDaily
    ? "Needs 3 scored calls today to qualify"
    : "Needs 20 scored calls this month to qualify";

  if (loading) {
    return (
      <div className={`relative flex-1 rounded-2xl overflow-hidden bg-gradient-to-br ${gradientClass} p-5 min-h-[110px]`}>
        {/* shimmer */}
        <div className="absolute inset-0 -translate-x-full animate-[shimmer_1.5s_infinite] bg-gradient-to-r from-transparent via-white/20 to-transparent" />
        <div className="h-3 w-24 rounded-full bg-white/30 mb-4" />
        <div className="flex items-center gap-3">
          <div className={`w-12 h-12 rounded-full ${shimmerClass}`} />
          <div className="space-y-2">
            <div className="h-4 w-32 rounded-full bg-white/30" />
            <div className="h-3 w-20 rounded-full bg-white/20" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      title={FORMULA}
      className={`relative flex-1 rounded-2xl overflow-hidden bg-gradient-to-br ${gradientClass} p-5 shadow-lg`}
    >
      {/* decorative blobs */}
      <div className="absolute -top-6 -right-6 w-24 h-24 rounded-full bg-white/10 pointer-events-none" />
      <div className="absolute -bottom-8 -left-4 w-20 h-20 rounded-full bg-white/10 pointer-events-none" />

      {/* label */}
      <p className="font-label text-[11px] font-bold text-white/80 uppercase tracking-widest mb-3">
        {label}
      </p>

      {winner ? (
        <div className="flex items-center gap-4">
          {/* Avatar */}
          <div
            className={`w-12 h-12 rounded-full ${avatarClass} flex items-center justify-center shrink-0`}
          >
            <Initials name={winner.name} />
          </div>

          {/* Info */}
          <div className="min-w-0 flex-1">
            <p className="text-white font-bold text-xl leading-tight truncate">
              {winner.name}
            </p>
            <p className="text-white/75 text-sm mt-0.5 font-medium">
              <span className="text-white font-bold text-base">{winner.points.toFixed(1)}</span> pts
              <span className="text-white/60 text-xs ml-2">
                · avg score {winner.avg_score.toFixed(1)} · {winner.total_calls} calls
              </span>
            </p>
          </div>

          {/* Trophy */}
          <div className="shrink-0 text-3xl select-none drop-shadow-sm">
            {isDaily ? "🏅" : "🏆"}
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-full bg-white/20 flex items-center justify-center text-xl">
            {isDaily ? "⏳" : "🎯"}
          </div>
          <p className="text-white/70 text-sm font-medium">{emptyMsg}</p>
        </div>
      )}
    </div>
  );
}

export default function WinnerBanner() {
  const [data, setData] = useState<WinnersData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.callers
      .winners()
      .then(setData)
      .catch(() => setData({ daily: null, monthly: null }))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mb-7">
      <div className="flex flex-col gap-4 sm:flex-row">
        <WinnerCard type="daily" winner={data?.daily ?? null} loading={loading} />
        <WinnerCard type="monthly" winner={data?.monthly ?? null} loading={loading} />
      </div>
      <p className="mt-2 font-label text-xs text-on-surface-muted sm:hidden">{FORMULA}</p>
    </div>
  );
}
