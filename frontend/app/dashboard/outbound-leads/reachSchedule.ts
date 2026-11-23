// Reach scheduling hours. The backend refuses a schedule outside 9 AM to 9 PM India time
// (routes/upload.py SCHEDULE_FROM_HOUR_IST / SCHEDULE_UNTIL_HOUR_IST); this only warns early.
export const SCHEDULE_FROM_HOUR_IST = 9;
export const SCHEDULE_UNTIL_HOUR_IST = 21;
export const SCHEDULE_HOURS_NOTE = "Campaigns can only be scheduled between 9 AM and 9 PM India time.";

const IST_OFFSET_MS = (5 * 60 + 30) * 60 * 1000;

function hourOk(hourIst: number): boolean {
  return hourIst >= SCHEDULE_FROM_HOUR_IST && hourIst < SCHEDULE_UNTIL_HOUR_IST;
}

/** `local` is the value of an <input type="datetime-local"> (wall-clock in the browser's own zone). */
export function scheduleProblem(local: string): string | null {
  if (!local) return null;
  const at = new Date(local);
  if (Number.isNaN(at.getTime())) return null;
  const hourIst = new Date(at.getTime() + IST_OFFSET_MS).getUTCHours();
  return hourOk(hourIst) ? null : "That time is outside 9 AM to 9 PM India time. Pick a time in the day.";
}

/** `hhmm` is the value of an <input type="time">; a drip's daily time is already India time. */
export function dripTimeProblem(hhmm: string): string | null {
  if (!hhmm) return null;
  const hour = Number(hhmm.split(":")[0]);
  if (Number.isNaN(hour)) return null;
  return hourOk(hour) ? null : "That time is outside 9 AM to 9 PM India time. Pick a time in the day.";
}

/** "about 4 minutes left" from how fast it has gone so far; null until there is enough to judge. */
export function timeLeftText(done: number, total: number, elapsedMs: number): string | null {
  if (done < 3 || elapsedMs < 3000 || done >= total) return null;
  const msLeft = ((total - done) * elapsedMs) / done;
  const min = Math.round(msLeft / 60000);
  if (min < 1) return "less than a minute left";
  return `about ${min} ${min === 1 ? "minute" : "minutes"} left`;
}
