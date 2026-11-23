import { apiFetch } from "@/lib/api";

/** Settings > Payments & advance: the shop's on/off switch for automatic balance reminders.
 *  Reading needs Orders access (deals.view); changing it is owner only. On unless turned off. */
export const balanceRemindersApi = {
  get: () => apiFetch<{ on: boolean }>("/api/v1/orders/balance-reminders"),
  set: (on: boolean) =>
    apiFetch<{ on: boolean }>("/api/v1/orders/balance-reminders", { method: "PUT", body: JSON.stringify({ on }) }),
};

/** What the switch says under its title, in the shop's words. */
export function remindersLine(on: boolean): string {
  return on
    ? "On: customers get a reminder on days 1, 3 and 7 while money is still to pay."
    : "Off: no automatic reminders. You can still send a payment link yourself.";
}
