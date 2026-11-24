import { describe, expect, it } from "vitest";
import { numberJobGroups, pickOptions, pickState, type JobNumber, type NumberJobs } from "./NumberJobsPanel";

const main: JobNumber = { id: "m", display_name: "Astro Tamil", number: "+919000088088", role: "primary", reach_block: null, send_block: null };
const standby: JobNumber = { id: "s", display_name: "AstroTamil", number: "+919000081088", role: "standby", reach_block: null, send_block: null };
const red: JobNumber = { id: "r", display_name: "Offers", number: "+916300077889", role: "standby", reach_block: "Rated red by Meta", send_block: null };

const auto: NumberJobs = { default_sender_id: "m", main_id: "m", reach_ids: ["s", "m"], picks: { alerts: null, otp: null, reach: null } };
type Groups = ReturnType<typeof numberJobGroups>;
const find = (groups: Groups, job: string) => groups.flatMap((g) => g.rows).find((r) => r.job === job)!;

describe("numberJobGroups", () => {
  const groups = numberJobGroups(auto, [main, standby]);

  it("sends every reply, AI or team, from the number the customer wrote to", () => {
    expect(find(groups, "AI agent replies").sender).toEqual({ kind: "their-number" });
    expect(find(groups, "Your team's replies in Chats").sender).toEqual({ kind: "their-number" });
  });

  it("runs Automatic campaigns Main first, then Standby as backup", () => {
    const s = find(groups, "Reach campaigns").sender;
    expect(s.kind === "rotation" && s.numbers.map((n) => n.id)).toEqual(["m", "s"]);
  });

  it("only alerts, OTP codes and Reach have a dropdown", () => {
    const picks = groups.flatMap((g) => g.rows).filter((r) => r.pick).map((r) => r.pick);
    expect(picks.sort()).toEqual(["alerts", "otp", "reach"]);
  });

  it("uses the picked numbers", () => {
    const g = numberJobGroups({ ...auto, picks: { otp: "s", alerts: "s", reach: "s" } }, [main, standby]);
    expect(find(g, "OTP codes").sender).toEqual({ kind: "number", number: standby });
    expect(find(g, "Alerts to you and staff").sender).toEqual({ kind: "number", number: standby });
    expect(find(g, "Reach campaigns").sender).toEqual({ kind: "number", number: standby });
    expect(find(g, "Bills, orders and bookings").sender).toEqual({ kind: "number", number: main });
  });
});

describe("pickState", () => {
  it("keeps a Reach pick whose cap is used (the rest waits) but drops a red one", () => {
    const capped = { ...standby, reach_block: "Today's cap used" };
    expect(pickState("reach", { ...auto, picks: { reach: "s" } }, [main, capped]).inUse).toBe(true);
    expect(pickState("reach", { ...auto, picks: { reach: "r" } }, [main, red]).inUse).toBe(false);
  });
});

describe("pickOptions", () => {
  it("greys out numbers that can't do the job, with the reason", () => {
    const opts = pickOptions("reach", auto, [main, standby, red]);
    expect(opts[0]).toMatchObject({ value: "auto", label: "Automatic: Main, then Standby" });
    const r = opts.find((o) => o.value === "r")!;
    expect(r.disabled).toBe(true);
    expect(String(r.label)).toContain("Rated red by Meta");
    expect(opts.find((o) => o.value === "s")!.disabled).toBe(false);
    // a red number can still carry OTP codes and alerts
    expect(pickOptions("otp", auto, [main, standby, red]).find((o) => o.value === "r")!.disabled).toBe(false);
  });
});

describe("Automatic campaigns", () => {
  it("leave a red number out of the backups", () => {
    const g = numberJobGroups({ ...auto, reach_ids: ["m", "s", "r"] }, [main, standby, red]);
    const s = find(g, "Reach campaigns").sender;
    expect(s.kind === "rotation" && s.numbers.map((n) => n.id)).toEqual(["m", "s"]);
  });
});
