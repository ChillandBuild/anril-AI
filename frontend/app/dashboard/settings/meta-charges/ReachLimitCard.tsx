"use client";

import { useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import useSWR from "swr";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { SectionCard } from "@/app/dashboard/otp/otpUi";
import { LoadError, Skeleton } from "@/app/dashboard/sms/ui";
import { connectionsApi } from "@/lib/connectionsApi";
import { reachLimitProblem } from "./chargesText";

export default function ReachLimitCard() {
  const { role, permissions } = useAuthRole();
  const canEdit = role === "owner" || permissions.includes("settings.manage");
  const { data, error, isLoading, mutate } = useSWR("connections:reach-limit", connectionsApi.reachLimit, {
    revalidateOnFocus: false,
  });
  // null = the person has not typed; show the saved number.
  const [text, setText] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const title = "Broadcasts per person";
  const description =
    "The most Reach broadcasts one person can get in a week (Sunday to Saturday). Bills, order updates, reminders and replies don't count.";

  if (error) {
    return (
      <SectionCard title={title} description={description}>
        <LoadError message={error instanceof Error ? error.message : "Something went wrong."} onRetry={() => mutate()} />
      </SectionCard>
    );
  }
  if (isLoading || !data) {
    return (
      <SectionCard title={title} description={description}>
        <Skeleton className="h-10 w-full max-w-[160px]" />
      </SectionCard>
    );
  }

  const value = text ?? String(data.weekly_limit);
  const problem = reachLimitProblem(value, data.min, data.max);
  const dirty = value.trim() !== String(data.weekly_limit);
  const showProblem = dirty && problem;
  const canSave = dirty && !problem && !saving;

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    try {
      const res = await connectionsApi.saveReachLimit(Number(value.trim()));
      await mutate({ ...data!, weekly_limit: res.weekly_limit }, { revalidate: false });
      setText(null);
      toast.success("Saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <SectionCard title={title} description={description}>
      <form onSubmit={(e) => void save(e)}>
        <label htmlFor="reach-weekly-limit" className="block text-sm font-semibold text-ink">
          Per week
        </label>
        <div className="mt-1.5 flex items-center gap-3">
          <div className="w-24 shrink-0">
            <input
              id="reach-weekly-limit"
              className="input h-10"
              inputMode="numeric"
              value={value}
              onChange={(e) => setText(e.target.value)}
              disabled={!canEdit || saving}
              aria-invalid={showProblem ? true : undefined}
              aria-describedby="reach-weekly-limit-help"
            />
          </div>
          {canEdit ? (
            <button type="submit" disabled={!canSave} className="btn-primary h-10">
              {saving ? <Loader2 size={14} className="animate-spin" aria-hidden /> : null}
              {saving ? "Saving…" : "Save"}
            </button>
          ) : null}
        </div>
      </form>
      {showProblem ? (
        <p className="mt-2 text-sm font-semibold text-danger" role="alert">
          {problem}
        </p>
      ) : null}
      <p id="reach-weekly-limit-help" className="mt-2 text-sm text-ink-secondary">
        New clients start at {data.default}. Meta may still block some marketing messages if a person gets too many from all businesses.
      </p>
    </SectionCard>
  );
}
