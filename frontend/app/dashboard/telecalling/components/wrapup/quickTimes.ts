/** Tomorrow at the given hour (0-23), minutes zero, in the device's local time. */
export function tomorrowAt(hour: number, now: Date): Date {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, hour, 0, 0, 0);
}

/** One-tap hour choices for "Tomorrow at...". */
export const TOMORROW_HOURS: { hour: number; label: string }[] = [
  { hour: 9, label: "9 AM" },
  { hour: 10, label: "10 AM" },
  { hour: 11, label: "11 AM" },
  { hour: 12, label: "12 PM" },
  { hour: 14, label: "2 PM" },
  { hour: 16, label: "4 PM" },
  { hour: 18, label: "6 PM" },
];
