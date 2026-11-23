"use client";
import { usePathname } from "next/navigation";
import { SettingsFormProvider } from "./SettingsFormContext";

/** Text size is open to everyone (it only changes their own screen), so it skips the
 * settings form provider, which shows only "Change password" to people without settings.view. */
const OPEN_TO_ALL = "/dashboard/settings/display";
/** Your account (profile, password, passkeys) is for every teammate; it still needs the provider for the profile. */
const YOUR_ACCOUNT = "/dashboard/settings/your-account";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  if (pathname === OPEN_TO_ALL || pathname.startsWith(`${OPEN_TO_ALL}/`)) return <>{children}</>;
  const openToAll = pathname === YOUR_ACCOUNT || pathname.startsWith(`${YOUR_ACCOUNT}/`);
  return <SettingsFormProvider openToAll={openToAll}>{children}</SettingsFormProvider>;
}
