"use client";
import { usePathname } from "next/navigation";
import { SettingsFormProvider } from "./SettingsFormContext";

/** Text size is open to everyone (it only changes their own screen), so it skips the
 * settings form provider, which shows only "Change password" to people without settings.view. */
const OPEN_TO_ALL = "/dashboard/settings/display";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  if (pathname === OPEN_TO_ALL || pathname.startsWith(`${OPEN_TO_ALL}/`)) return <>{children}</>;
  return <SettingsFormProvider>{children}</SettingsFormProvider>;
}
