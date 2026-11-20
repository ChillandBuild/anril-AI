import { describe, expect, it } from "vitest";
import { buildNavAccess } from "./useNavAccess";

const base = { role: "caller" as const, permissions: [] as string[], enabledFeatures: [] as string[], subStatus: "active" };

describe("buildNavAccess", () => {
  it("owners pass every permission check; callers only their own", () => {
    const owner = buildNavAccess({ ...base, role: "owner" }).access;
    expect(owner.can("anything")).toBe(true);
    expect(owner.canSettings).toBe(true);
    const caller = buildNavAccess({ ...base, permissions: ["settings.view"] }).access;
    expect(caller.can("leads.view")).toBe(false);
    expect(caller.canSettings).toBe(true);
    expect(caller.canAny(["leads.view", "settings.view"])).toBe(true);
  });

  it("messaging flags come from the enabled features", () => {
    const a = buildNavAccess({ ...base, enabledFeatures: ["inbound_messaging", "sms"] }).access;
    expect(a).toMatchObject({ inboundOn: true, outboundOn: false, messagingOn: true, smsOn: true });
  });

  it("brain needs an active subscription, messaging and brain.view", () => {
    const features = ["outbound_messaging"];
    expect(buildNavAccess({ ...base, enabledFeatures: features, permissions: ["brain.view"] }).access.brainGate).toBe(true);
    expect(buildNavAccess({ ...base, enabledFeatures: features, permissions: ["brain.view"], subStatus: "expired" }).access.brainGate).toBe(false);
    expect(buildNavAccess({ ...base, enabledFeatures: [], permissions: ["brain.view"] }).access.brainGate).toBe(false);
  });

  it("telecalling shows only when bought, subscribed and at least one page is allowed", () => {
    const features = ["telecalling_sim", "telecalling.dialer"];
    const ok = buildNavAccess({ ...base, enabledFeatures: features, permissions: ["telecalling.dialer"] });
    expect(ok.access.telecallingVisible).toBe(true);
    expect(ok.tcGroupItems.map((i) => i.href)).toEqual(["/dashboard/telecalling"]);
    expect(buildNavAccess({ ...base, enabledFeatures: features, permissions: [] }).access.telecallingVisible).toBe(false);
    expect(buildNavAccess({ ...base, enabledFeatures: [], permissions: ["telecalling.dialer"] }).access.telecallingVisible).toBe(false);
  });
});
