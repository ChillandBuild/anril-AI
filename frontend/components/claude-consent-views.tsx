import Link from "next/link";
import { AnrilLogo } from "@/components/logo";
import { consentLoginHref, type ConsentDetails } from "@/lib/claude-access";

/**
 * What the Claude consent page shows, one card per state. Pure: everything comes in through props,
 * so each state can be rendered and checked without a browser or a login.
 *
 * Every card sits in the same frame ("Connect to Claude") and, once we know which connector is
 * asking, carries a pill: "Admin connector" (Anril Admin) or "Client connector" (Anril AI).
 */

export type Connector = "admin" | "client";

export type Phase =
  | { name: "loading" }
  | { name: "missing" }
  | { name: "signed_out" }
  | { name: "not_admin"; email: string }
  | { name: "ready"; details: Extract<ConsentDetails, { kind: "pending" }>; email: string }
  | { name: "client_ready"; details: Extract<ConsentDetails, { kind: "pending" }>; email: string; business: string; dailyCap: number }
  | { name: "client_refused"; why: string }
  | { name: "continue"; redirectUrl: string; host: string; connector: Connector; email: string; business?: string }
  | { name: "already_consented"; admin: boolean }
  | { name: "cancelled" }
  | { name: "done" }
  | { name: "error"; message: string };

export type Busy = "allow" | "deny" | null;

export interface ConsentViewProps {
  phase: Phase;
  busy: Busy;
  actionError: string | null;
  authorizationId: string;
  onAllow: () => void;
  /** Cancel on an allow card (tells Supabase) or on the reconnect card (just closes the offer). */
  onCancel: () => void;
  onContinue: () => void;
  onRetry: () => void;
}

const CONNECTOR_NAME: Record<Connector, string> = { admin: "Anril Admin", client: "Anril AI" };
const CONNECTOR_PILL: Record<Connector, string> = { admin: "Admin connector", client: "Client connector" };

const PRIMARY_BTN =
  "flex-1 bg-primary hover:bg-primary-dark text-white font-medium py-2.5 rounded-xl text-sm transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 font-display";
const SECONDARY_BTN =
  "flex-1 border border-border rounded-xl py-2.5 text-sm font-medium text-ink-secondary hover:bg-surface-mid transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 font-display";

function Frame({ connector, children }: { connector?: Connector; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="flex justify-center mb-2">
            <AnrilLogo className="h-7 w-auto text-ink" />
          </div>
          <p className="text-xs text-ink-muted mt-1.5 uppercase tracking-widest font-semibold font-label">
            Connect to Claude
          </p>
        </div>
        <div className="bg-white rounded-card shadow-card border border-border p-8">
          {connector && (
            <span
              data-testid="connector-pill"
              className="inline-block mb-3 px-2.5 py-0.5 rounded-full bg-surface-mid text-xs font-semibold text-ink-secondary font-label"
            >
              {CONNECTOR_PILL[connector]}
            </span>
          )}
          {children}
        </div>
      </div>
    </div>
  );
}

function Title({ children }: { children: React.ReactNode }) {
  return <h1 className="text-base font-bold text-ink font-display">{children}</h1>;
}

function Text({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <p className={`text-sm text-ink-secondary mt-2 font-body ${className}`}>{children}</p>;
}

/** Who is signing in, and in what role. Shown on every card that asks the person to go ahead. */
function Who({ email, role }: { email: string; role: string }) {
  return (
    <div data-testid="who" className="mt-4 rounded-xl bg-surface-mid px-3.5 py-2.5 font-body">
      <p className="text-xs text-ink-muted">Signing in as</p>
      <p className="text-sm font-semibold text-ink break-all">{email || "your Anril account"}</p>
      <p className="text-xs text-ink-secondary mt-0.5">{role}</p>
    </div>
  );
}

function ErrorBox({ children }: { children: React.ReactNode }) {
  return (
    <div role="alert" className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-body">
      {children}
    </div>
  );
}

function Actions({
  busy, onCancel, onPrimary, primary, primaryBusy, cancelBusy = "Cancelling...",
}: {
  busy: Busy;
  onCancel: () => void;
  onPrimary: () => void;
  primary: string;
  primaryBusy: string;
  cancelBusy?: string;
}) {
  return (
    <div className="flex gap-3 mt-5">
      <button type="button" onClick={onCancel} disabled={busy !== null} className={SECONDARY_BTN}>
        {busy === "deny" ? cancelBusy : "Cancel"}
      </button>
      <button type="button" onClick={onPrimary} disabled={busy !== null} className={PRIMARY_BTN}>
        {busy === "allow" ? primaryBusy : primary}
      </button>
    </div>
  );
}

export function ConsentView(props: ConsentViewProps) {
  const { phase, busy, actionError, authorizationId, onAllow, onCancel, onContinue, onRetry } = props;

  switch (phase.name) {
    case "loading":
      return (
        <Frame>
          <div className="flex flex-col items-center text-center py-4" role="status" aria-live="polite">
            <div
              aria-hidden="true"
              className="h-7 w-7 rounded-full border-2 border-border border-t-primary animate-spin"
            />
            <p className="mt-4 text-base font-bold text-ink font-display">Checking your connection</p>
            <p className="mt-1 text-sm text-ink-secondary font-body">This takes a moment.</p>
          </div>
        </Frame>
      );

    case "missing":
      return (
        <Frame>
          <Title>Nothing to approve</Title>
          <Text>
            This page opens from the Claude app when you connect it. Start from the Claude app, or go to{" "}
            <Link href="/operator/mcp" className="text-primary hover:underline">
              Operator Console → MCP
            </Link>
            .
          </Text>
        </Frame>
      );

    case "signed_out":
      return (
        <Frame>
          <Title>Sign in to Anril first</Title>
          <Text>Sign in to Anril in a new tab, then come back here and continue.</Text>
          <a
            href="/login"
            target="_blank"
            rel="noopener noreferrer"
            className="mt-4 block w-full text-center bg-primary hover:bg-primary-dark text-white font-medium py-2.5 rounded-xl text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 font-display"
          >
            Sign in to Anril
          </a>
          <button type="button" onClick={onRetry} className={`${SECONDARY_BTN} mt-3 w-full flex-none`}>
            I have signed in, continue
          </button>
          <p className="text-xs text-ink-muted mt-4 font-body">
            Anril operator?{" "}
            <Link href={consentLoginHref(authorizationId)} className="text-primary hover:underline">
              Sign in to the Operator Console
            </Link>
            .
          </p>
        </Frame>
      );

    case "client_refused":
      return (
        <Frame connector="client">
          <Title>This account cannot connect Claude</Title>
          <Text>{phase.why}</Text>
        </Frame>
      );

    case "not_admin":
      return (
        <Frame connector="admin">
          <Title>Only an Anril system admin can allow this</Title>
          <Text>
            {phase.email ? `You are signed in as ${phase.email}, which is not a system admin.` : "You are not signed in as a system admin."}{" "}
            Ask a system admin to connect Claude.
          </Text>
        </Frame>
      );

    case "continue": {
      const name = CONNECTOR_NAME[phase.connector];
      const line =
        phase.connector === "admin"
          ? "Claude can read Anril operator data, read only."
          : "Claude can use your Anril account, as set in Settings.";
      const role = phase.connector === "admin" ? "System admin" : phase.business ? `Owner of ${phase.business}` : "Account owner";
      return (
        <Frame connector={phase.connector}>
          <Title>Reconnect Claude to {name}</Title>
          <Text>{line}</Text>
          <Who email={phase.email} role={role} />
          <Actions busy={busy} onCancel={onCancel} onPrimary={onContinue} primary="Continue" primaryBusy="Continue" />
          <p className="text-xs text-ink-muted mt-4 font-body">
            Only continue if you started this from your own Claude app. If someone sent you this link, close the page.
          </p>
          <p className="text-xs text-ink-muted mt-1.5 font-body">You will go back to {phase.host}</p>
        </Frame>
      );
    }

    case "already_consented":
      if (!phase.admin) {
        return (
          <Frame connector="client">
            <Title>Claude is switched off for your account</Title>
            <Text>
              You allowed Claude before and then disconnected it. To connect again, open Anril → Settings → Anril AI
              for Claude, press Clear old approval, then connect from the Claude app. If that does not work, ask your
              Anril account manager.
            </Text>
          </Frame>
        );
      }
      return (
        <Frame connector="admin">
          <Title>Claude is already approved</Title>
          <Text>
            Open{" "}
            <Link href="/operator/mcp" className="text-primary hover:underline">
              Operator Console → MCP
            </Link>
            . The connection is switched off there. Press Reset sign-in on that page, then connect again from the
            Claude app to see the Allow screen.
          </Text>
        </Frame>
      );

    case "cancelled":
      return (
        <Frame>
          <Title>Cancelled</Title>
          <Text>Nothing was connected. You can close this page.</Text>
        </Frame>
      );

    case "done":
      return (
        <Frame>
          <p role="status" className="text-sm font-semibold text-success text-center font-body">
            Connected. You can go back to Claude.
          </p>
        </Frame>
      );

    case "error":
      return (
        <Frame>
          <div role="alert" className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-body">
            {phase.message}
          </div>
          <button type="button" onClick={onRetry} className={`${SECONDARY_BTN} mt-4 w-full flex-none`}>
            Try again
          </button>
        </Frame>
      );

    case "client_ready":
      return (
        <Frame connector="client">
          <Title>Allow {CONNECTOR_NAME.client} to use your account?</Title>
          <Who email={phase.email} role={`Owner of ${phase.business}`} />
          <ul className="list-disc pl-[18px] mt-4 space-y-1.5 text-sm text-ink-secondary font-body">
            <li>Read your leads, phone numbers, chats, calls and broadcasts</li>
            <li>Assign leads and add notes to them</li>
            <li className="text-danger">
              Send WhatsApp messages, up to {phase.dailyCap.toLocaleString("en-IN")} a day
            </li>
          </ul>
          <p className="text-xs text-ink-muted mt-4 font-body">
            What Claude reads here (lead names, phone numbers and chats) is sent to Claude, which is run by Anthropic.
            It cannot touch payments, your team, settings or any other business.
          </p>
          {actionError && <ErrorBox>{actionError}</ErrorBox>}
          <Actions busy={busy} onCancel={onCancel} onPrimary={onAllow} primary="Allow" primaryBusy="Allowing..." />
          <p className="text-xs text-ink-muted mt-4 font-body">
            You can switch this off, or change the daily limit, any time in Anril → Settings.
          </p>
        </Frame>
      );

    case "ready":
      return (
        <Frame connector="admin">
          <Title>Allow {CONNECTOR_NAME.admin} to read operator data?</Title>
          <Who email={phase.email} role="System admin" />
          <ul className="list-disc pl-[18px] mt-4 space-y-1.5 text-sm text-ink-secondary font-body">
            <li>Read every client&apos;s leads, phone numbers and chats</li>
            <li>Read health, usage, AI spend and audit log</li>
            <li className="text-danger">Cannot send, change or delete anything</li>
          </ul>
          {actionError && <ErrorBox>{actionError}</ErrorBox>}
          <Actions busy={busy} onCancel={onCancel} onPrimary={onAllow} primary="Allow" primaryBusy="Allowing..." />
          <p className="text-xs text-ink-muted mt-4 font-body">
            You can switch this off any time in Operator Console → MCP.
          </p>
        </Frame>
      );
  }
}
