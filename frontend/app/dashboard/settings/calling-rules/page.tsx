"use client";

import { useCallback, useEffect, useState } from "react";
import { PhoneCall } from "lucide-react";
import { toast } from "sonner";
import { AiraLoader } from "@/components/AiraLoader";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { ComingLater, ErrorBox, InShort, PageHeader } from "../payments/MyBusinessUi";
import { PeopleCard } from "@/components/call-iq-settings/PeopleCard";
import { RulesCard } from "@/components/call-iq-settings/RulesCard";
import { rulesProblem, sameRules } from "@/components/call-iq-settings/callRulesLogic";
import { callRulesApi, type CallRules, type RulesPeople } from "@/lib/callRulesApi";

export default function CallingRulesPage() {
  const { role, permissions } = useAuthRole();
  const isOwner = role === "owner";
  const canEdit = isOwner || permissions.includes("settings.manage");
  const canLeave = isOwner || permissions.includes("team.manage");

  const [saved, setSaved] = useState<CallRules | null>(null);
  const [draft, setDraft] = useState<CallRules | null>(null);
  const [people, setPeople] = useState<RulesPeople | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setState("loading");
    try {
      const [r, p] = await Promise.all([callRulesApi.rules(), callRulesApi.people()]);
      setSaved(r);
      setDraft(r);
      setPeople(p);
      setState("ready");
    } catch {
      setState("error");
    }
  }, []);

  const reloadPeople = useCallback(async () => {
    try {
      setPeople(await callRulesApi.people());
    } catch {
      toast.error("Could not refresh the list.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      const r = await callRulesApi.saveRules(draft);
      setSaved(r);
      setDraft(r);
      toast.success("Rules saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the rules");
    } finally {
      setSaving(false);
    }
  }

  const problem = draft ? rulesProblem(draft) : null;
  const dirty = !!(draft && saved && !sameRules(draft, saved));

  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 pb-10">
      <PageHeader icon={PhoneCall} title="Calling rules" subtitle="When telecallers can call, how many calls a day, who uses a SIM, and leave." />

      {state === "loading" ? <AiraLoader inline className="min-h-[200px]" /> : null}
      {state === "error" ? <ErrorBox message="Couldn't load this page." onRetry={() => void load()} /> : null}

      {state === "ready" && draft && people ? (
        <>
          <InShort>
            {draft.calling_hours_on ? "Telecallers can call only inside the calling hours." : "Telecallers can call at any time."}{" "}
            {draft.daily_limit_on ? `Each can make ${draft.daily_limit} calls a day.` : "There is no daily limit."}
          </InShort>
          <RulesCard draft={draft} onChange={(p) => setDraft((d) => (d ? { ...d, ...p } : d))} canEdit={canEdit}
            dirty={dirty} saving={saving} problem={problem} onSave={() => void save()} />
          <PeopleCard data={people} canMode={canEdit} canLeave={canLeave} onChanged={() => void reloadPeople()} />
          <ComingLater items={["National Do Not Disturb list check", "IVR menu", "Missed call to WhatsApp", "Recording settings"]} />
        </>
      ) : null}
    </div>
  );
}
