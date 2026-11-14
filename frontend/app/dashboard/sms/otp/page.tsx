import { OtpConsole } from "../DeveloperTab";
import { OtpHistory } from "../ReportsTab";

export default function SmsOtpPage() {
  return (
    <div className="space-y-4">
      <OtpConsole />
      <OtpHistory />
    </div>
  );
}
