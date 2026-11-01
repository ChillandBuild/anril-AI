import localFont from "next/font/local";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { serverFetchJson } from "@/lib/serverApi";
import { ClientLayout } from "./ClientLayout";

const inter = localFont({
  src: "../fonts/inter-variable.ttf",
  variable: "--font-swiss",
  display: "swap",
  weight: "100 900",
});

interface OnboardingStatus {
  has_tenant: boolean;
  is_system_admin?: boolean;
}

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  // Timeout-guarded so a cold backend can't hang SSR into a white screen.
  // null (backend down/slow) → fall through to the dashboard, never block.
  const status = await serverFetchJson<OnboardingStatus>("/api/v1/onboarding/status", token);

  // redirect() must live OUTSIDE any try/catch — it throws NEXT_REDIRECT, and
  // the previous catch {} swallowed it, silently breaking onboarding routing.
  if (status && !status.has_tenant) {
    // Operator accounts are system_admins with no tenant — send them to the
    // operator console, not the client onboarding flow.
    redirect(status.is_system_admin ? "/operator" : "/dashboard/onboarding");
  }

  return (
    <div className={inter.variable}>
      <ClientLayout>
        {children}
      </ClientLayout>
    </div>
  );
}
