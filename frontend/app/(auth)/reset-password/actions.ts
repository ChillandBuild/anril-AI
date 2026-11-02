"use server";
import { cookies } from "next/headers";
import { RESET_COOKIE } from "@/lib/auth-redirect";

// The recovery cookie is httpOnly, so the browser can't drop it itself once the
// new password is saved. One use per link.
export async function clearRecoveryCookie() {
  cookies().delete({ name: RESET_COOKIE, path: "/reset-password" });
}
