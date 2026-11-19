import { describe, expect, it } from "vitest";
import type { OAuthAuthorizationDetails, OAuthRedirect } from "@supabase/supabase-js";
import {
  consentLoginHref,
  formatCallArguments,
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
