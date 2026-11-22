/** Follow-up wait times. Stored as delay_hours; shown as hours or days. */

export const HOURS_PER_DAY = 24;
export const MAX_DELAY_DAYS = 30;
export const MAX_DELAY_HOURS = MAX_DELAY_DAYS * HOURS_PER_DAY;

export type DelayUnit = "hours" | "days";

/** True from 24 hours on: WhatsApp only allows an approved template then. */
export const isDayStep = (hours: number): boolean => hours >= HOURS_PER_DAY;

/** "2 hrs", "Day 3". A whole number of days from 24h on reads "Day N", anything else "N hrs". */
export function formatDelay(hours: number): string {
  if (isDayStep(hours) && hours % HOURS_PER_DAY === 0) return `Day ${hours / HOURS_PER_DAY}`;
  return hours === 1 ? "1 hr" : `${hours} hrs`;
}

/** The number + unit to show in the editor for a stored delay. */
export function splitDelay(hours: number): { value: number; unit: DelayUnit } {
  if (isDayStep(hours) && hours % HOURS_PER_DAY === 0) return { value: hours / HOURS_PER_DAY, unit: "days" };
  return { value: hours, unit: "hours" };
}

/** Stored delay_hours for what was typed, or null when it isn't a whole number from 1 to 30 days. */
export function toDelayHours(value: number, unit: DelayUnit): number | null {
  if (!Number.isInteger(value) || value < 1) return null;
  const hours = unit === "days" ? value * HOURS_PER_DAY : value;
  return hours <= MAX_DELAY_HOURS ? hours : null;
}
