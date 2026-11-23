/** The "kept on time" figure on the Scheduled calls page (calls made within 15 minutes of their time, last 30 days). */
export interface KeptOnTime {
  kept: number;
  due: number;
  percent: number | null;
  days: number;
}

export function keptHeadline(stats: KeptOnTime | null): string {
  if (!stats || stats.percent === null) return "—";
  return `${stats.percent}%`;
}

export function keptDetail(stats: KeptOnTime | null): string {
  if (!stats) return "";
  if (stats.due === 0) return `No scheduled calls have fallen due in the last ${stats.days} days.`;
  return `${stats.kept} of ${stats.due} scheduled calls were made within 15 minutes of their time (last ${stats.days} days).`;
}
