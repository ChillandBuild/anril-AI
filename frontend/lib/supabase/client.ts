import { createBrowserClient } from "@supabase/ssr";
import { OPERATOR_AUTH_COOKIE, isOperatorPath } from "./operator";

const options = { auth: { experimental: { passkey: true } } };

let client: ReturnType<typeof createBrowserClient> | null = null;
let operatorClient: ReturnType<typeof createBrowserClient> | null = null;

export type LoginScope = "dashboard" | "operator";

// Set by the one page that serves both sides (the Claude consent screen), which must pick the login
// by which connector is asking and not by its address. null = go by the address.
let forcedScope: LoginScope | null = null;

export function setLoginScope(scope: LoginScope | null) {
  forcedScope = scope;
}

function wantsOperator(): boolean {
  if (forcedScope) return forcedScope === "operator";
  return typeof window !== "undefined" && isOperatorPath(window.location.pathname);
}

/**
 * The Supabase client for the page being shown: pages under /operator get the operator login,
 * everything else gets the dashboard login (see ./operator.ts for why they are kept apart).
 */
export function createClient() {
  if (wantsOperator()) {
    if (!operatorClient) {
      operatorClient = createBrowserClient(
        process.env.NEXT_PUBLIC_SUPABASE_URL!,
        process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
        { ...options, cookieOptions: { name: OPERATOR_AUTH_COOKIE } }
      );
    }
    return operatorClient;
  }
  if (!client) {
    client = createBrowserClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      options
    );
  }
  return client;
}
