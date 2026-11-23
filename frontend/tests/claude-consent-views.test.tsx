/**
 * The Claude consent page, one check per state: the right frame, the right connector pill and
 * the right account. Rendered to plain HTML, so no browser or login is needed.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ConsentView, type Phase } from "@/components/claude-consent-views";

const noop = () => {};

function render(phase: Phase, extra: { actionError?: string | null } = {}) {
  return renderToStaticMarkup(
    <ConsentView
      phase={phase}
      busy={null}
      actionError={extra.actionError ?? null}
      authorizationId="auth-123"
      onAllow={noop}
      onCancel={noop}
      onContinue={noop}
      onRetry={noop}
    />,
  );
}

const pending = {
  kind: "pending" as const,
  authorizationId: "auth-123",
  clientId: "client-abc",
  clientName: "Claude",
  email: "x@example.com",
};

function pill(html: string): string | null {
  const m = html.match(/data-testid="connector-pill"[^>]*>([^<]+)</);
  return m ? m[1] : null;
}

describe("consent page states", () => {
  it("every state uses the neutral Connect to Claude frame, never Operator Console", () => {
    const phases: Phase[] = [
      { name: "loading" },
      { name: "missing" },
      { name: "signed_out" },
      { name: "not_admin", email: "a@b.com" },
      { name: "ready", details: pending, email: "developer@airaai.com" },
      { name: "client_ready", details: pending, email: "owner@shop.com", business: "AstroTamil", dailyCap: 500 },
      { name: "client_refused", why: "Only the owner can connect Claude." },
      { name: "continue", redirectUrl: "https://claude.ai/cb", host: "claude.ai", connector: "admin", email: "a@b.com" },
      { name: "already_consented", admin: true },
      { name: "already_consented", admin: false },
      { name: "cancelled" },
      { name: "done" },
      { name: "error", message: "boom" },
    ];
    for (const phase of phases) {
      const html = render(phase);
      expect(html, phase.name).toContain("Connect to Claude");
      expect(html, phase.name).not.toContain("Operator Console</p>");
    }
  });

  it("loading shows a spinner and a message, not empty grey bars", () => {
    const html = render({ name: "loading" });
    expect(html).toContain("Checking your connection");
    expect(html).toContain("This takes a moment.");
    expect(html).toContain('role="status"');
    expect(html).not.toContain("animate-pulse");
    expect(pill(html)).toBeNull();
  });

  it("admin reconnect: admin pill, admin title, the admin's email and role, Cancel and Continue", () => {
    const html = render({
      name: "continue", redirectUrl: "https://claude.ai/cb", host: "claude.ai",
      connector: "admin", email: "developer@airaai.com",
    });
    expect(pill(html)).toBe("Admin connector");
    expect(html).toContain("Reconnect Claude to Anril Admin");
    expect(html).toContain("Claude can read Anril operator data, read only.");
    expect(html).toContain("Signing in as");
    expect(html).toContain("developer@airaai.com");
    expect(html).toContain("System admin");
    expect(html).toContain(">Cancel<");
    expect(html).toContain(">Continue<");
    expect(html).toContain("If someone sent you this link, close the page.");
  });

  it("client reconnect: client pill, client title, owner email and business", () => {
    const html = render({
      name: "continue", redirectUrl: "https://claude.ai/cb", host: "claude.ai",
      connector: "client", email: "astrotamiloffice@gmail.com", business: "AstroTamil",
    });
    expect(pill(html)).toBe("Client connector");
    expect(html).toContain("Reconnect Claude to Anril AI");
    expect(html).toContain("Claude can use your Anril account, as set in Settings.");
    expect(html).toContain("astrotamiloffice@gmail.com");
    expect(html).toContain("Owner of AstroTamil");
    expect(html).not.toContain("System admin");
  });

  it("client reconnect without a business name still names the role", () => {
    const html = render({
      name: "continue", redirectUrl: "https://claude.ai/cb", host: "claude.ai",
      connector: "client", email: "owner@shop.com",
    });
    expect(html).toContain("Account owner");
    expect(html).not.toContain("Owner of undefined");
  });

  it("admin first-time allow: admin pill, admin title, read-only bullets", () => {
    const html = render({ name: "ready", details: pending, email: "developer@airaai.com" });
    expect(pill(html)).toBe("Admin connector");
    expect(html).toContain("Allow Anril Admin to read operator data?");
    expect(html).toContain("developer@airaai.com");
    expect(html).toContain("System admin");
    expect(html).toContain("Cannot send, change or delete anything");
    expect(html).toContain(">Allow<");
    expect(html).toContain(">Cancel<");
  });

  it("client first-time allow: client pill, owner and business, daily cap", () => {
    const html = render({
      name: "client_ready", details: pending, email: "astrotamiloffice@gmail.com",
      business: "AstroTamil", dailyCap: 1500,
    });
    expect(pill(html)).toBe("Client connector");
    expect(html).toContain("Allow Anril AI to use your account?");
    expect(html).toContain("astrotamiloffice@gmail.com");
    expect(html).toContain("Owner of AstroTamil");
    expect(html).toContain("up to 1,500 a day");
    expect(html).not.toContain("System admin");
  });

  it("an allow error shows in an alert", () => {
    const html = render({ name: "ready", details: pending, email: "a@b.com" }, { actionError: "Could not allow access" });
    expect(html).toContain('role="alert"');
    expect(html).toContain("Could not allow access");
  });

  it("refusals and switched-off states carry the right pill", () => {
    expect(pill(render({ name: "client_refused", why: "Only the owner can connect Claude." }))).toBe("Client connector");
    expect(pill(render({ name: "not_admin", email: "a@b.com" }))).toBe("Admin connector");
    expect(pill(render({ name: "already_consented", admin: true }))).toBe("Admin connector");
    expect(pill(render({ name: "already_consented", admin: false }))).toBe("Client connector");
  });

  it("signed out links back to the operator login for this request", () => {
    const html = render({ name: "signed_out" });
    expect(html).toContain("Sign in to Anril first");
    expect(html).toContain("/operator/login?next=");
    expect(html).toContain("auth-123");
  });

  it("cancelled and error states", () => {
    expect(render({ name: "cancelled" })).toContain("Nothing was connected.");
    const err = render({ name: "error", message: "This app is not an approved Anril connector." });
    expect(err).toContain("This app is not an approved Anril connector.");
    expect(err).toContain("Try again");
  });
});
