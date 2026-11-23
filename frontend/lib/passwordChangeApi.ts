import { apiFetch } from "@/lib/api";

/** First sign-in: the server checks the given password, saves the new one, and clears the
 *  "must change password" flag that the person cannot clear on their own. */
export const passwordChangeApi = {
  firstPassword: (current_password: string, new_password: string) =>
    apiFetch<{ changed: boolean }>("/api/v1/first-setup/new-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),
};
