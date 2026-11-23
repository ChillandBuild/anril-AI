import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("createClient picks the login by the forced scope", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://proj.supabase.co");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "anon-key");
  });
  afterEach(() => vi.unstubAllEnvs());

  it("gives the operator and the dashboard different clients, and the same one each time", async () => {
    const { createClient, setLoginScope } = await import("./client");
    setLoginScope("dashboard");
    const dashboard = createClient();
    setLoginScope("operator");
    const operator = createClient();
    expect(operator).not.toBe(dashboard);
    expect(createClient()).toBe(operator);
    setLoginScope("dashboard");
    expect(createClient()).toBe(dashboard);
    setLoginScope(null);
    expect(createClient()).toBe(dashboard); // no window here: goes by the default (dashboard)
  });
});
