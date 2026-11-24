import { describe, expect, it } from "vitest";
import { PICK_ROWS, pickOptions, pickState, type JobNumber, type NumberJobs } from "./NumberJobsPanel";

const main: JobNumber = { id: "m", display_name: "Astro Tamil", number: "+919000088088", role: "primary", reach_block: null, send_block: null };
const standby: JobNumber = { id: "s", display_name: "AstroTamil", number: "+919000081088", role: "standby", reach_block: null, send_block: null };
const red: JobNumber = { id: "r", display_name: "Offers", number: "+916300077889", role: "standby", reach_block: "Rated red by Meta", send_block: null };

const auto: NumberJobs = { default_sender_id: "m", main_id: "m", reach_ids: ["s", "m"], picks: { alerts: null, otp: null, reach: null } };

describe("Which number does what", () => {
  it("only has dropdowns for Reach, OTP codes and alerts", () => {
    expect(PICK_ROWS.map((r) => r.job)).toEqual(["reach", "otp", "alerts"]);
  });
});

describe("pickState", () => {
  it("uses a picked number that can send", () => {
    expect(pickState("otp", { ...auto, picks: { otp: "s" } }, [main, standby])).toEqual({ picked: standby, inUse: true, why: null });
    expect(pickState("otp", auto, [main, standby]).picked).toBeNull();
  });

  it("keeps a Reach pick whose cap is used (the rest waits) but drops a red one", () => {
    const capped = { ...standby, reach_block: "Today's cap used" };
    expect(pickState("reach", { ...auto, picks: { reach: "s" } }, [main, capped]).inUse).toBe(true);
    expect(pickState("reach", { ...auto, picks: { reach: "r" } }, [main, red]).inUse).toBe(false);
  });
});

describe("pickOptions", () => {
  it("starts with Automatic and greys out numbers that can't do the job, with the reason", () => {
    const opts = pickOptions("reach", auto, [main, standby, red]);
    expect(opts[0]).toMatchObject({ value: "auto", text: "Automatic" });
    const r = opts.find((o) => o.value === "r")!;
    expect(r.disabled).toBe(true);
    expect(r.text).toContain("Rated red by Meta");
    expect(opts.find((o) => o.value === "s")!.disabled).toBe(false);
  });

  it("lets a red number carry OTP codes and alerts", () => {
    const opts = pickOptions("otp", auto, [main, standby, red]);
    expect(opts[0].value).toBe("auto");
    expect(opts.find((o) => o.value === "r")!.disabled).toBe(false);
  });
});
