import { createClient } from "@/lib/supabase/server";
import { serverFetchJson } from "@/lib/serverApi";
import { DialView } from "./DialView";

interface TeamMe {
  role: "owner" | "caller";
  caller_id: string | null;
  permissions?: string[];
}

/** Call IQ > Calling > Dial a number. Same server-seeded role as the Dialer page, minus the queue data. */
export default async function DialPage() {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const me = await serverFetchJson<TeamMe>("/api/v1/team/me", token);

  return (
    <DialView
      initialRole={me?.role ?? null}
      initialCallerId={me?.caller_id ?? null}
      initialPermissions={me?.permissions ?? []}
    />
  );
}
