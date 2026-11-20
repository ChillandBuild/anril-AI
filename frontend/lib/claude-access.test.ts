import { describe, expect, it } from "vitest";
import type { OAuthAuthorizationDetails, OAuthRedirect } from "@supabase/supabase-js";
import {
  capUsage,
  consentLoginHref,
  describeClientAction,
  formatCallArguments,
  parseDailyCap,
  isSafeRedirectUrl,
  mapAuthorizationDetails,
  safeOperatorNext,
} from "./claude-access";

describe("safeOperatorNext", () => {
  it("allows the consent screen with its query string", () => {
    const next = "/operator/oauth/consent?authorization_id=abc-123";
    expect(safeOperatorNext(next)).toBe(next);
  });

  it.each([
    null,
    undefined,
    "",
    "/operator",
    "/operator/oauth/consent",
    "/operator/claude-access",
    "//evil.com",
    "https://evil.com/operator/oauth/consent?x=1",
    "/\\evil.com",
    "/operator/oauth/consent?x=1\\..\\evil",
    "/operator/oauth/consent?x=1 \nLocation: evil",
    "javascript:alert(1)",
  ])("ignores %s", (value) => {
    expect(safeOperatorNext(value)).toBeNull();
  });

  it("ignores an absurdly long value", () => {
    expect(safeOperatorNext(`/operator/oauth/consent?${"a".repeat(2100)}`)).toBeNull();
  });
});

describe("consentLoginHref", () => {
  it("encodes the way back and the result passes safeOperatorNext", () => {
    const href = consentLoginHref("a b&c=d");
    expect(href.startsWith("/operator/login?next=")).toBe(true);
    const next = new URLSearchParams(href.split("?")[1]).get("next");
    expect(next).toBe("/operator/oauth/consent?authorization_id=a%20b%26c%3Dd");
    expect(safeOperatorNext(next)).toBe(next);
  });
});

describe("mapAuthorizationDetails", () => {
  const pending: OAuthAuthorizationDetails = {
    authorization_id: "auth-1",
    redirect_uri: "https://claude.ai/api/mcp/auth_callback",
    client: { id: "client-uuid", name: "Claude", uri: "https://claude.ai", logo_uri: "" },
    user: { id: "user-1", email: "prem@anril.example" },
    scope: "openid",
  };

  it("maps a pending authorization", () => {
    expect(mapAuthorizationDetails(pending)).toEqual({
      kind: "pending",
      authorizationId: "auth-1",
      clientId: "client-uuid",
      clientName: "Claude",
      email: "prem@anril.example",
    });
  });

  it("falls back to Claude when the client has no name", () => {
    const result = mapAuthorizationDetails({ ...pending, client: { ...pending.client, name: " " } });
    expect(result.kind === "pending" && result.clientName).toBe("Claude");
  });

  it("maps the already-consented shape (redirect only, no client id)", () => {
    const redirect: OAuthRedirect = { redirect_url: "https://claude.ai/cb?code=x" };
    expect(mapAuthorizationDetails(redirect)).toEqual({
      kind: "already_consented",
      redirectUrl: "https://claude.ai/cb?code=x",
    });
  });
});

describe("isSafeRedirectUrl", () => {
  it("accepts only https addresses on Claude's own sites", () => {
    expect(isSafeRedirectUrl("https://claude.ai/api/mcp/auth_callback?code=x")).toBe(true);
    expect(isSafeRedirectUrl("https://claude.com/api/mcp/auth_callback?code=x")).toBe(true);
  });

  it.each([
    null,
    undefined,
    "",
    "/relative",
    "javascript:alert(1)",
    "data:text/html,x",
    "not a url",
    "http://claude.ai/api/mcp/auth_callback",
    "https://evil.example/cb?code=x",
    "https://claude.ai.evil.example/cb",
    "https://notclaude.ai/cb",
    "claude://callback?code=x",
  ])(
    "rejects %s",
    (value) => {
      expect(isSafeRedirectUrl(value)).toBe(false);
    },
  );
});

describe("formatCallArguments", () => {
  it("joins key and value, skipping empty ones", () => {
    expect(formatCallArguments({ lead: "Ravi K", page: 1, note: "", gone: null })).toBe("lead Ravi K · page 1");
  });

  it("stringifies nested values and handles empty input", () => {
    expect(formatCallArguments({ filter: { a: 1 } })).toBe('filter {"a":1}');
    expect(formatCallArguments(null)).toBe("");
    expect(formatCallArguments({})).toBe("");
  });
});

describe("describeClientAction", () => {
  const row = (action: string, tool: string | null, args: Record<string, unknown> = {}, ok: boolean | null = true) =>
    describeClientAction({ action, tool, ok, arguments: args });

  it("says what a send was, and marks it as a send", () => {
    expect(row("claude.send", "send_reply", { lead_id: "L1", text: "Your chart is ready" })).toEqual({
      kind: "send", text: 'Reply to a lead: "Your chart is ready"',
    });
    expect(row("claude.send", "send_reply", { lead_id: "L1", template_id: "T1" }).text).toBe("Template message to a lead");
    expect(row("claude.send", "send_broadcast", { template_name: "diwali_offer" }).text).toBe("Broadcast: diwali_offer");
  });

  it("describes edits and reads from the cut-down audit arguments", () => {
    expect(row("claude.edit", "assign_lead", { team_member: "Karthik R" })).toEqual({ kind: "edit", text: "Assigned a lead to Karthik R" });
    expect(row("claude.edit", "assign_lead", { team_member: "" }).text).toBe("Unassigned a lead");
    expect(row("claude.read", "find_leads", { search: "phone ending 4471", limit: 20 })).toEqual({
      kind: "ask", text: "Searched leads: phone ending 4471",
    });
    expect(row("claude.read", "find_leads").text).toBe("Listed leads");
    expect(row("claude.read", "preview_broadcast", { template_name: "diwali_offer" }).text).toBe("Previewed a broadcast: diwali_offer");
    expect(row("claude.read", "my_business").text).toBe("Looked at your business summary");
  });

  it("keeps long text short, flags failures and survives a tool it does not know", () => {
    const long = row("claude.send", "send_reply", { text: "x".repeat(300) }).text;
    expect(long.length).toBeLessThan(90);
    expect(row("claude.send", "send_broadcast", { template_name: "diwali_offer" }, false).text).toBe("Not done: Broadcast: diwali_offer");
    expect(row("claude.read", "some_new_tool")).toEqual({ kind: "ask", text: "some new tool" });
    expect(row("claude.read", null).text).toBe("Used Anril AI");
  });

  it("names the owner's own switches", () => {
    expect(row("claude.connection.allow", null)).toEqual({ kind: "setting", text: "Claude was connected" });
    expect(row("claude.connection.revoke", null).text).toBe("Claude was disconnected");
    expect(row("claude.cap.change", null).text).toBe("The daily sending limit was changed");
  });
});

describe("parseDailyCap", () => {
  it("accepts whole numbers from 0 to the ceiling", () => {
    expect(parseDailyCap("500", 10000)).toBe(500);
    expect(parseDailyCap(" 0 ", 10000)).toBe(0);
    expect(parseDailyCap("10000", 10000)).toBe(10000);
  });

  it.each(["", "abc", "-1", "12.5", "1e3", "10001", "5 00"])("rejects %s", (value) => {
    expect(parseDailyCap(value, 10000)).toBeNull();
  });
});

describe("capUsage", () => {
  it("gives the meter's fill and what is left", () => {
    expect(capUsage(42, 500)).toEqual({ percent: 8.4, left: 458 });
    expect(capUsage(0, 500)).toEqual({ percent: 0, left: 500 });
  });

  it("is full at or past the limit, and when the limit is 0", () => {
    expect(capUsage(500, 500)).toEqual({ percent: 100, left: 0 });
    expect(capUsage(620, 500)).toEqual({ percent: 100, left: 0 });
    expect(capUsage(0, 0)).toEqual({ percent: 100, left: 0 });
  });
});
