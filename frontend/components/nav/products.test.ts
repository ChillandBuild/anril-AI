import { describe, expect, it, vi } from "vitest";
import { canSeeAgents, productHref, productOf, PRODUCT_HOME } from "./products";

describe("productOf", () => {
  it("puts /dashboard/agents and its pages in Agents", () => {
    expect(productOf("/dashboard/agents")).toBe("agents");
    expect(productOf("/dashboard/agents/characters/abc")).toBe("agents");
  });

  it("puts every other dashboard page in Anril", () => {
    expect(productOf("/dashboard")).toBe("anril");
    expect(productOf("/dashboard/inbound-leads")).toBe("anril");
    // A lookalike path is not the Agents product.
    expect(productOf("/dashboard/agentsfoo")).toBe("anril");
  });
});

describe("productHref", () => {
  it("returns to the last page you had open in the other product", () => {
    const last = { anril: "/dashboard/inbound-leads", agents: "/dashboard/agents/characters" };
    expect(productHref("anril", "/dashboard/agents/keys", last)).toBe("/dashboard/inbound-leads");
    expect(productHref("agents", "/dashboard/inbound-leads", last)).toBe("/dashboard/agents/characters");
  });

  it("goes home when you click the product you are already in", () => {
    const last = { anril: "/dashboard/inbound-leads", agents: "/dashboard/agents/keys" };
    expect(productHref("agents", "/dashboard/agents/keys", last)).toBe(PRODUCT_HOME.agents);
    expect(productHref("anril", "/dashboard/inbound-leads", last)).toBe(PRODUCT_HOME.anril);
  });

  it("falls back to the home page when nothing was remembered", () => {
    expect(productHref("agents", "/dashboard", {})).toBe("/dashboard/agents");
  });

  it("keeps the query string of a remembered page", () => {
    expect(productHref("agents", "/dashboard", { agents: "/dashboard/agents?tab=x" })).toBe("/dashboard/agents?tab=x");
  });

  it("ignores a remembered path that belongs to the other product", () => {
    expect(productHref("anril", "/dashboard/agents", { anril: "/dashboard/agents/keys" })).toBe("/dashboard");
    expect(productHref("anril", "/dashboard/agents", { anril: "https://evil.example" })).toBe("/dashboard");
  });
});


describe("canSeeAgents", () => {
  it("lets the owner and roles with companions.manage in", () => {
    expect(canSeeAgents("owner", [])).toBe(true);
    expect(canSeeAgents("caller", ["companions.manage"])).toBe(true);
  });

  it("keeps everyone else out, settings.manage alone included", () => {
    expect(canSeeAgents("caller", ["settings.manage"])).toBe(false);
    expect(canSeeAgents(null, [])).toBe(false);
  });
});

describe("Sales | Agents switch", () => {
  it("labels Anril as Sales", async () => {
    const { PRODUCT_LABEL } = await import("./products");
    expect(PRODUCT_LABEL).toEqual({ anril: "Sales", agents: "Agents" });
  });

  it("marks <html> at once on a click and stops animating later", async () => {
    vi.useFakeTimers();
    const dataset: Record<string, string> = {};
    vi.stubGlobal("document", { documentElement: { dataset } });
    const { startProductSwitch } = await import("./products");
    startProductSwitch("agents");
    expect(dataset).toEqual({ product: "agents", productAnim: "" });
    vi.advanceTimersByTime(3000);
    expect(dataset).toEqual({ product: "agents" });
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });
});
