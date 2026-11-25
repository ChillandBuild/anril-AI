import type { AdvanceOptions } from "@/lib/myBusinessApi";

/** True when the two sets of switches differ (either may be missing, which counts as "nothing to compare"). */
export function optionsChanged(saved: AdvanceOptions | null, draft: AdvanceOptions | null): boolean {
  if (!saved || !draft) return false;
  return saved.staff_can_change !== draft.staff_can_change || saved.ai_pay_full !== draft.ai_pay_full;
}

/** True when the balance-reminder switch was flipped (null = could not be read, so nothing to save). */
export function remindersChanged(saved: boolean | null, draft: boolean | null): boolean {
  return saved != null && draft != null && saved !== draft;
}
