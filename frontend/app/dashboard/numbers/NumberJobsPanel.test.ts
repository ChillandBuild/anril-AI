import { describe, expect, it } from "vitest";
import { numberJobGroups, type JobNumber } from "./NumberJobsPanel";

const main: JobNumber = { id: "m", display_name: "Demo Silks", number: "+919000011223", role: "primary" };
const standby: JobNumber = { id: "s", display_name: "Offers", number: "+919800044556", role: "standby" };
const extra: JobNumber = { id: "x", display_name: "OTP line", number: "+916300077889", role: "extra" };

const rows = (groups: ReturnType<typeof numberJobGroups>) => groups.flatMap((g) => g.rows);
const find = (groups: ReturnType<typeof numberJobGroups>, job: string) => rows(groups).find((r) => r.job === job)!;

describe("numberJobGroups", () => {
  const groups = numberJobGroups({ default_sender_id: "m", main_id: "m", reach_ids: ["s", "m"] }, [main, standby, extra]);

  it("sends every reply, AI or team, from the number the customer wrote to", () => {
    expect(find(groups, "AI agent replies").sender).toEqual({ kind: "their-number" });
    expect(find(groups, "Your team's replies in Chats").sender).toEqual({ kind: "their-number" });
  });

  it("runs campaigns Main first, then Standby, never Extra", () => {
    const s = find(groups, "Reach campaigns").sender;
    expect(s.kind === "rotation" && s.numbers.map((n) => n.id)).toEqual(["m", "s"]);
  });

  it("sends automatic messages, OTP, bills and alerts from the default sender", () => {
    for (const job of ["New leads from ads", "IndiaMART and JustDial leads", "Auto-Messages and follow-ups", "OTP codes", "Bills, orders and bookings", "Alerts to you and staff"]) {
      expect(find(groups, job).sender).toEqual({ kind: "number", number: main });
    }
  });

  it("says campaigns are paused when no number can send them", () => {
    const g = numberJobGroups({ default_sender_id: "m", main_id: "m", reach_ids: [] }, [main]);
    expect(find(g, "Reach campaigns").sender).toEqual({ kind: "rotation", numbers: [] });
  });
});
