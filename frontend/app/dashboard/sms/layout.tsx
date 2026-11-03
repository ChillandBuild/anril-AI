import type { ReactNode } from "react";
import { SmsShell } from "./SmsShell";

export default function SmsLayout({ children }: { children: ReactNode }) {
  return <SmsShell>{children}</SmsShell>;
}
