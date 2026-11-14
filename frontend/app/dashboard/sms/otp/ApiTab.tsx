import { OtpDocs } from "./OtpDocs";
import { OtpKeysCard } from "./OtpKeysCard";

export function OtpApiTab() {
  return (
    <div className="space-y-4">
      <OtpKeysCard />
      <OtpDocs />
    </div>
  );
}
