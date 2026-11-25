import { describe, expect, it } from "vitest";
import { quickActionsFor } from "./quickActions";

const ids = (input: Parameters<typeof quickActionsFor>[0]) => quickActionsFor(input).map((a) => a.id);

describe("quickActionsFor", () => {
  it("shows all three to an owner", () => {
    expect(ids({ role: "owner", permissions: [], enabledFeatures: ["outbound_messaging"] })).toEqual(["new-bill", "new-template", "broadcast"]);
  });
  it("shows nothing to a telecaller with no matching permissions", () => {
    expect(ids({ role: "caller", permissions: ["leads.view"], enabledFeatures: ["outbound_messaging"] })).toEqual([]);
  });
  it("shows only New bill to a manager with deals.manage", () => {
    expect(ids({ role: "caller", permissions: ["deals.manage"], enabledFeatures: ["outbound_messaging"] })).toEqual(["new-bill"]);
  });
  it("hides New template and Broadcast when outbound messaging is off", () => {
    expect(ids({ role: "owner", permissions: [], enabledFeatures: [] })).toEqual(["new-bill"]);
  });
  it("needs the manage permission, not just view", () => {
    expect(ids({ role: "caller", permissions: ["templates.view", "outbound_leads.view"], enabledFeatures: ["outbound_messaging"] })).toEqual([]);
  });
});
