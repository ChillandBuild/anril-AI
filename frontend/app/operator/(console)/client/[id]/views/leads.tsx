"use client";
import { useEffect, useState } from "react";
import { Users, TrendingUp, UserCheck } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { StatCard } from "../components/stat-card";
import { SkeletonCard, SkeletonTable } from "../components/skeleton";

async function apiFetch<T>(path: string): Promise<T> {
  const auth = await getAuthHeaders();
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...auth },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail || "Request failed");
  }
  return res.json() as Promise<T>;
}

function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.abs(diff) / 1000;
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

interface LeadRow {
  id: string;
  name: string | null;
  phone: string | null;
  segment: string;
  score: number;
  source: string | null;
  created_at: string;
}

interface LeadsData {
  total: number;
  segments: { A: number; B: number; C: number; D: number };
  recent: LeadRow[];
}

const SEGMENT_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  A: { bg: "bg-green-50", text: "text-success", label: "Hot" },
  B: { bg: "bg-amber-50", text: "text-warning", label: "Warm" },
  C: { bg: "bg-blue-50", text: "text-blue-600", label: "Cold" },
  D: { bg: "bg-stone-100", text: "text-ink-muted", label: "Not interested" },
};

export function LeadsView({ tenantId, subSection }: { tenantId: string; subSection: "segments" | "inbound" | "outbound" }) {
  const [data, setData] = useState<LeadsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    const direction = subSection === "segments" ? "all" : subSection;
    apiFetch<LeadsData>(`/api/v1/operator/clients/${tenantId}/dashboard/leads?direction=${direction}`)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [tenantId, subSection]);

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard />
        </div>
        <SkeletonTable rows={6} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-danger/20 rounded-xl text-sm text-danger">
        {error}
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-6">
      {subSection === "segments" ? (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <StatCard icon={<Users size={18} />} label="Total" value={data.total} tone="border-t-sky-400" />
          {(["A", "B", "C", "D"] as const).map((seg) => {
            const style = SEGMENT_STYLES[seg];
            const segBorder = seg === "A" ? "border-t-emerald-400" : seg === "B" ? "border-t-amber-400" : seg === "C" ? "border-t-blue-400" : "border-t-slate-400";
            return (
              <div key={seg} className={`${style.bg} rounded-card border border-border border-t-4 ${segBorder} p-5 shadow-sm`}>
                <div className="flex items-center gap-2 mb-2">
                  <span className={`text-xs font-medium uppercase tracking-wider font-label ${style.text}`}>
                    {seg} — {style.label}
                  </span>
                </div>
                <p className={`text-2xl font-bold ${style.text}`}>{data.segments[seg]?.toLocaleString() ?? 0}</p>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          <StatCard icon={<TrendingUp size={18} />} label={`${subSection} Leads`} value={data.total} tone="border-t-sky-400" />
          <StatCard icon={<UserCheck size={18} />} label="Hot (A)" value={data.segments.A} tone="border-t-emerald-400" />
        </div>
      )}

      {data.recent.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-ink-muted">
          <Users size={40} className="mb-3 opacity-40" />
          <p className="text-sm">No leads found</p>
        </div>
      ) : (
        <div className="bg-white rounded-card border border-border overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-surface-mid text-ink-secondary uppercase text-xs">
                <th className="text-left px-4 py-3 font-medium">Name</th>
                <th className="text-left px-4 py-3 font-medium">Phone</th>
                <th className="text-left px-4 py-3 font-medium">Segment</th>
                <th className="text-left px-4 py-3 font-medium">Score</th>
                <th className="text-left px-4 py-3 font-medium">Source</th>
                <th className="text-left px-4 py-3 font-medium">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {data.recent.map((lead) => {
                const seg = SEGMENT_STYLES[lead.segment] || SEGMENT_STYLES.D;
                return (
                  <tr key={lead.id} className="hover:bg-surface-mid/50 transition-colors">
                    <td className="px-4 py-3 font-medium text-ink">{lead.name || "Unknown"}</td>
                    <td className="px-4 py-3 text-ink-secondary font-mono text-xs">{lead.phone || "—"}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${seg.bg} ${seg.text}`}>
                        {lead.segment} — {seg.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-ink">{lead.score}</td>
                    <td className="px-4 py-3 text-ink-secondary text-xs">{lead.source || "—"}</td>
                    <td className="px-4 py-3 text-ink-muted text-xs">{relTime(lead.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
