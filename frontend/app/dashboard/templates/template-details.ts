/**
 * "Customer detail" choices for the template body box.
 *
 * A WhatsApp template only has numbered blanks, {{1}}, {{2}}... The number carries no meaning:
 * whoever sends the template decides what fills each blank. So the picker is honest about
 * which details Anril really fills, and which ones the owner has to supply when sending.
 *
 * What Anril fills at send time (checked in the code, not assumed):
 *  - Auto-messages: "Customer's first name", "Customer's full name", "Customer's number",
 *    "Page they came from" (VAR_SOURCES in auto-messages/shared.ts; backend/app/services/auto_messages.py).
 *  - WhatsApp alerts: lead name, lead phone, business name, enquiry date, chat link...
 *    (FIELDS in backend/app/services/template_fields.py, picked in variable-map-editor.tsx).
 *  - Broadcasts (Reach): {{1}} is the lead's name unless a sheet column is picked; every other
 *    blank is a sheet column the owner picks (outbound-leads/page.tsx, template_params.py).
 * Nothing in Anril fills "order amount", "order number" or "booking date" by itself: for those the
 * owner picks a sheet column (broadcast) or sends the value from their app ("Value your app sends").
 */

export type DetailGroup = "filled" | "supplied";

export type CustomerDetail = {
  id: string;
  /** Plain words shown to the owner, also the chip label: "{{1}} = Customer name". */
  label: string;
  /** Example value Meta's reviewer sees. Never sent to customers. */
  sample: string;
  group: DetailGroup;
  /** Short line under the label: where this gets filled. */
  hint: string;
};

export const CUSTOMER_DETAILS: CustomerDetail[] = [
  { id: "customer_name", label: "Customer name", sample: "Priya", group: "filled", hint: "First name. Auto-messages and alerts fill it. Reach fills it when it is {{1}}." },
  { id: "customer_full_name", label: "Customer full name", sample: "Priya Raman", group: "filled", hint: "Auto-messages fill it." },
  { id: "phone_number", label: "Phone number", sample: "98765 43210", group: "filled", hint: "Auto-messages and alerts fill it." },
  { id: "business_name", label: "Business name", sample: "Sunrise Stores", group: "filled", hint: "Alerts fill it." },
  { id: "enquiry_date", label: "Enquiry date", sample: "14 Oct 2026", group: "filled", hint: "Alerts fill it." },
  { id: "order_amount", label: "Order amount", sample: "₹1,499", group: "supplied", hint: "You pick the sheet column, or your app sends it." },
  { id: "order_number", label: "Order number", sample: "#1048", group: "supplied", hint: "You pick the sheet column, or your app sends it." },
  { id: "booking_time", label: "Booking date and time", sample: "14 Oct, 5:30 PM", group: "supplied", hint: "You pick the sheet column, or your app sends it." },
];

export const DETAIL_GROUP_TITLES: Record<DetailGroup, string> = {
  filled: "Anril fills these when it sends",
  supplied: "You choose where these come from when you send",
};

/** The next free {{n}}: one more than the highest number already in the text. */
export function nextVarNumber(used: number[]): number {
  return used.length ? Math.max(...used) + 1 : 1;
}

/** Chip text for a variable: "{{1}} = Customer name", or just "{{1}}" when no detail was picked. */
export function variableChip(n: number, labels: Record<number, string>): string {
  const label = labels[n];
  return label ? `{{${n}}} = ${label}` : `{{${n}}}`;
}
