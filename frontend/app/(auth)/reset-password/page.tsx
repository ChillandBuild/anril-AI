import Link from "next/link";
import { cookies } from "next/headers";
import { AnrilLogo } from "@/components/logo";
import { createClient } from "@/lib/supabase/server";
import { RESET_COOKIE } from "@/lib/auth-redirect";
import a from "@/components/auth/auth.module.css";
import ResetPasswordForm from "./ResetPasswordForm";

export const dynamic = "force-dynamic";

// Reached only through /auth/callback after a recovery link is exchanged. The
// form shows only while the short-lived recovery cookie and the session it came
// with are both present; anyone else gets the expired state.
export default async function ResetPasswordPage() {
  const recovering = cookies().get(RESET_COOKIE)?.value === "1";
  let ready = false;
  if (recovering) {
    const supabase = await createClient();
    const { data } = await supabase.auth.getUser();
    ready = Boolean(data.user);
  }

  return (
    <div className={`${a.page} flex flex-col`}>
      <main className="flex-1 flex items-center justify-center px-4 py-8 sm:px-8">
        <div className="flex w-full max-w-[420px] flex-col gap-5">
          <div className={a.card}>
            <AnrilLogo height={30} className="text-ink mb-7" />
            {ready ? (
              <>
                <h1 className="text-[26px] font-extrabold tracking-tight">
                  Choose a new password
                </h1>
                <p className="mt-1 mb-6 text-[15px] text-ink-muted">
                  At least 8 characters. You&apos;ll stay signed in.
                </p>
                <ResetPasswordForm />
              </>
            ) : (
              <>
                <h1 className="text-[26px] font-extrabold tracking-tight">
                  This link has expired
                </h1>
                <p className="mt-1 mb-6 text-[15px] text-ink-muted">
                  Reset links work once, for 15 minutes, in the browser that
                  asked for them. Request a new one from the sign-in page.
                </p>
                <Link
                  href="/login"
                  className={`${a.primary} flex items-center justify-center`}
                >
                  Back to sign in
                </Link>
              </>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
