"use client";
import { useCallback, useEffect, useState } from "react";
import { Check, KeyRound } from "lucide-react";
import { operatorFetch, relTime } from "@/lib/operator";

interface HelpRequest {
  id: string;
  identifier: string;
  business_name: string | null;
  note: string | null;
  status: "open" | "done";
  created_at: string;
  done_at: string | null;
}

type Filter = "open" | "done";

function RequestCard({ request, onDone }: { request: HelpRequest; onDone: () => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function markDone() {
    setSaving(true);
    setError(null);
    try {
      await operatorFetch(`/api/v1/password-help/requests/${request.id}/done`, { method: "POST" });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not mark it done");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-card border border-border bg-white p-4 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-ink break-words">{request.identifier}</p>
          <p className="text-xs text-ink-secondary">{request.business_name || "Business name not given"}</p>
        </div>
        <span className="shrink-0 text-xs text-ink-secondary">
          {request.status === "done" ? `Done ${relTime(request.done_at)}` : relTime(request.created_at)}
        </span>
      </div>
      {request.note && <p className="rounded-xl bg-surface-mid px-3 py-2 text-sm text-ink break-words">{request.note}</p>}
      {error && <p className="text-xs text-danger">{error}</p>}
      {request.status === "open" && (
        <button
          onClick={markDone}
          disabled={saving}
          className="inline-flex min-h-10 items-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-semibold text-white disabled:opacity-60"
        >
          <Check size={15} /> {saving ? "Saving…" : "Mark done (I called them back)"}
        </button>
      )}
    </div>
  );
}

export default function PasswordHelpPage() {
  const [filter, setFilter] = useState<Filter>("open");
  const [rows, setRows] = useState<HelpRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    return operatorFetch<{ data: HelpRequest[] }>(`/api/v1/password-help/requests?status=${filter}`)
      .then((res) => {
        setRows(res.data ?? []);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Request failed"))
      .finally(() => setLoading(false));
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6 p-4 sm:p-7">
      <div>
        <h1 className="font-display text-lg font-bold text-ink">Password help</h1>
        <p className="mt-0.5 text-xs text-ink-secondary">
          People who tapped &quot;Forgot password&quot; on the login page. Call them back, set a new password for them,
          then mark the request done.
        </p>
      </div>

      <div className="flex gap-2">
        {(["open", "done"] as const).map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            aria-pressed={filter === s}
            className={`min-h-10 rounded-xl px-4 text-xs font-medium capitalize transition-colors ${
              filter === s ? "bg-primary text-white" : "bg-surface-mid text-ink-secondary hover:text-ink"
            }`}
          >
            {s === "open" ? "Waiting" : "Done"}
          </button>
        ))}
      </div>

      {error && <div className="rounded-xl border border-danger/20 bg-red-50 p-3 text-sm text-danger">{error}</div>}

      {loading ? (
        <div className="text-sm text-ink-secondary">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="rounded-card border border-dashed border-border p-10 text-center">
          <KeyRound size={28} className="mx-auto mb-3 text-ink-secondary" />
          <p className="text-sm font-medium text-ink">{filter === "open" ? "Nobody is waiting for a password" : "Nothing done yet"}</p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {rows.map((r) => (
            <RequestCard key={r.id} request={r} onDone={load} />
          ))}
        </div>
      )}
    </div>
  );
}
