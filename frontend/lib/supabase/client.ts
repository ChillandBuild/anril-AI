import { createBrowserClient } from "@supabase/ssr";
import { OPERATOR_AUTH_COOKIE, isOperatorPath } from "./operator";

const options = { auth: { experimental: { passkey: true } } };

let client: ReturnType<typeof createBrowserClient> | null = null;
let operatorClient: ReturnType<typeof createBrowserClient> | null = null;

/**
 * The Supabase client for the page being shown: pages under /operator get the operator login,
 * everything else gets the dashboard login (see ./operator.ts for why they are kept apart).
 */
export function createClient() {
  if (typeof window !== "undefined" && isOperatorPath(window.location.pathname)) {
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
