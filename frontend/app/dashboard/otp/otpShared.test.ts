import { describe, expect, it } from "vitest";
import type { OtpView } from "@/lib/api";
import { otpTimeline } from "./otpShared";

const base: OtpView = {
  otp_id: "o1",
  phone: "+919876543210",
  mode: "sms_then_whatsapp",
  source: "anril",
  status: "pending",
  ref: null,
  expires_at: "2026-11-15T10:10:00Z",
  verified_at: null,
  sms: { status: "sent", error: null },
  whatsapp: { status: "none", error: null },
  whatsapp_backup_sent: false,
  not_requested: false,
  created_at: "2026-11-15T10:00:00Z",
};
const t = (iso: string) => iso.slice(11, 16);

describe("otpTimeline", () => {
  it("shows a waiting step while a channel is still moving", () => {
    expect(otpTimeline(base, t).map((s) => s.title)).toEqual(["Code made by Anril", "SMS sent", "Waiting for a delivery report…"]);
  });

  it("tells the SMS-then-WhatsApp backup story and ends on verified", () => {
    const steps = otpTimeline(
      {
        ...base,
        status: "verified",
        verified_at: "2026-11-15T10:02:00Z",
        sms: { status: "failed", error: "Absent subscriber" },
        whatsapp: { status: "read", error: null },
        whatsapp_backup_sent: true,
      },
      t,
    );
    expect(steps.map((s) => [s.title, s.tone])).toEqual([
      ["Code made by Anril", "info"],
      ["SMS not delivered", "danger"],
      ["WhatsApp backup read", "success"],
      ["Code verified", "success"],
    ]);
    expect(steps[1].detail).toBe("Absent subscriber");
    expect(steps[3].time).toBe("10:02");
  });

  it("skips unused channels and names client-made codes", () => {
    const steps = otpTimeline({ ...base, mode: "whatsapp", source: "client", sms: { status: "none", error: null }, whatsapp: { status: "delivered", error: null } }, t);
    expect(steps.map((s) => s.title)).toEqual(["Code received from your server", "WhatsApp delivered"]);
  });
});
