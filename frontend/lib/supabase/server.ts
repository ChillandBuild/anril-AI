import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { OPERATOR_AUTH_COOKIE } from "./operator";

export async function createClient() {
  return build(false);
}

/** The Operator Console's own login (separate cookie from the dashboard's). */
export async function createOperatorClient() {
  return build(true);
}

async function build(operator: boolean) {
  const cookieStore = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      ...(operator ? { cookieOptions: { name: OPERATOR_AUTH_COOKIE } } : {}),
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // setAll called from Server Component — middleware handles refresh
          }
        },
      },
    }
  );
}
