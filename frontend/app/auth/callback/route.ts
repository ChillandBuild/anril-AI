import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { RESET_COOKIE, RESET_COOKIE_MAX_AGE, safeNext } from "@/lib/auth-redirect";

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = safeNext(searchParams.get("next"));

  // Supabase sends an expired or already-used link here as ?error=...&error_code=otp_expired
  // with no code at all.
  if (!code || searchParams.get("error")) {
    return NextResponse.redirect(`${origin}/login?reason=link`);
  }

  const supabase = await createClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) {
    // Expired, already used, or opened in a different browser from the one
    // that asked for it (the PKCE verifier lives in that browser's cookies).
    return NextResponse.redirect(`${origin}/login?reason=link`);
  }

  const response = NextResponse.redirect(`${origin}${next}`);
  if (next === "/reset-password") {
    response.cookies.set(RESET_COOKIE, "1", {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/reset-password",
      maxAge: RESET_COOKIE_MAX_AGE,
    });
  }
  return response;
}
