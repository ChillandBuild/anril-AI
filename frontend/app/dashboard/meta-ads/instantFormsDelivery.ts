import type { InstantFormDelivery, InstantFormHelloStatus, InstantFormTemplateStatus } from "@/lib/api";

export interface DeliveryLook {
  label: string;
  className: string;
  /** Longer plain-words explanation for the tooltip. */
  hint: string;
}

/** What the leads table shows for a message we sent, from WhatsApp's own receipt.
 * null = nothing to add (no receipt yet, or the message never went out). */
export function deliveryLook(
  delivery: InstantFormDelivery | null | undefined,
  sentToCallingAt: string | null | undefined,
  templateStatus: InstantFormTemplateStatus,
): DeliveryLook | null {
  if (delivery === "no_whatsapp" || (templateStatus === "failed" && sentToCallingAt)) {
    return {
      label: sentToCallingAt ? "No WhatsApp, sent to calling" : "No WhatsApp",
      className: "bg-amber-50 text-amber-800",
      hint: sentToCallingAt
        ? "This number isn't on WhatsApp, so the person was sent to Call IQ to be called back."
        : "This number isn't on WhatsApp.",
    };
  }
  if (delivery === "read") {
    return { label: "Read", className: "bg-emerald-50 text-emerald-700", hint: "They opened the message." };
  }
  if (delivery === "delivered") {
    return { label: "Delivered", className: "bg-emerald-50 text-emerald-700", hint: "The message reached their phone." };
  }
  if (delivery === "failed") {
    return { label: "Not delivered", className: "bg-red-50 text-red-700", hint: "WhatsApp could not deliver this message." };
  }
  return null;
}

export interface HelloLook {
  label: string;
  /** The button to show, or null when there is nothing to press. */
  button: string | null;
  className: string;
}

/** The "Ready-made hello" line on the Instant forms tab. */
export function helloLook(status: InstantFormHelloStatus | undefined): HelloLook {
  switch (status) {
    case "approved":
      return { label: "Approved", button: null, className: "bg-emerald-50 text-emerald-700" };
    case "waiting":
      return { label: "Waiting for Meta", button: null, className: "bg-blue-50 text-blue-800" };
    case "rejected":
      return { label: "Meta did not approve it", button: "Send again", className: "bg-red-50 text-red-700" };
    default:
      return { label: "Not set up", button: "Set up", className: "bg-amber-50 text-amber-800" };
  }
}

/** What a form's "Template" cell says: its own template, the ready-made hello, or nothing. */
export function formTemplateText(
  form: { template_name: string | null; uses_hello?: boolean; auto_hello?: boolean },
  hello: InstantFormHelloStatus | undefined,
): { kind: "own" | "auto" | "auto_waiting" | "off" | "none"; text: string } {
  if (form.template_name) return { kind: "own", text: form.template_name };
  if (form.auto_hello === false) return { kind: "off", text: "Off" };
  if (form.uses_hello || hello === "approved") return { kind: "auto", text: "auto" };
  if (hello === "waiting") return { kind: "auto_waiting", text: "auto, once Meta approves" };
  return { kind: "none", text: "Not set" };
}
