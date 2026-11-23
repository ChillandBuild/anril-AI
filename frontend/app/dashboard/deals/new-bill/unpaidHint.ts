/** New bill: the line shown when the customer already owes on an order. Only a hint, it never merges bills. */
export function unpaidHintText(count: number): string {
  return `${count} unpaid ${count === 1 ? "order" : "orders"}`;
}
