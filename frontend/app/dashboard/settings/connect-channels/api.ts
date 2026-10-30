import { API_URL, getAuthHeaders } from "@/lib/api";
import type { Setting, SettingsMap } from "./channels";

export async function fetchSettings(): Promise<Setting[]> {
  const auth = await getAuthHeaders();
  const res = await fetch(`${API_URL}/api/v1/settings/`, { headers: auth });
  if (!res.ok) throw new Error("Failed to load settings");
  return (await res.json()).settings;
}

export async function saveSettings(updates: SettingsMap): Promise<void> {
  const auth = await getAuthHeaders();
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/v1/settings/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...auth },
      body: JSON.stringify({ updates }),
    });
  } catch {
    // Raw fetch rejects with a cryptic "Load failed" (Safari) on any network hiccup.
    throw new Error("Cannot reach the server. Check your connection and try again.");
  }
  if (!res.ok) {
    // Surface the backend's specific reason (e.g. invalid Telegram token) instead of a generic string.
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Failed to save settings");
  }
}

async function postSettings<T>(path: string, body?: unknown): Promise<T> {
  const auth = await getAuthHeaders();
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/v1/settings${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...auth },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error("Cannot reach the server. Check your connection and try again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Something went wrong. Please try again.");
  return data as T;
}

/** Connect with Razorpay, step 1: the Razorpay consent page to send the browser to. */
export async function startRazorpayOAuth(): Promise<string> {
  return (await postSettings<{ authorize_url: string }>("/razorpay/oauth/start")).authorize_url;
}

/** Step 2, from the callback page: hand Razorpay's code + state to the backend. */
export async function completeRazorpayOAuth(code: string, state: string): Promise<{ account_id: string }> {
  return postSettings<{ account_id: string }>("/razorpay/oauth/complete", { code, state });
}
