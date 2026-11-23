"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { NameStep } from "@/components/first-setup/WorkspaceSteps";
import { FirstSetupWizard } from "@/components/first-setup/FirstSetupWizard";

// First setup: name the workspace (only when there isn't one yet), then the 6 steps.
// See components/first-setup/FirstSetupWizard.tsx.
export default function OnboardingPage() {
  const router = useRouter();
  const [hasWorkspace, setHasWorkspace] = useState<boolean | null>(null);

  useEffect(() => {
    api.onboarding
      .status()
      .then((s) => setHasWorkspace(s.has_tenant))
      // If the check fails, assume the workspace exists: the Anril team usually creates it.
      .catch(() => setHasWorkspace(true));
  }, []);

  function finish() {
    router.push("/dashboard");
    router.refresh();
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-lg">
        {hasWorkspace === null && <div className="h-64 rounded-3xl bg-border-subtle animate-pulse" />}
        {hasWorkspace === false && <NameStep onCreated={() => setHasWorkspace(true)} />}
        {hasWorkspace && <FirstSetupWizard onFinish={finish} />}
      </div>
    </div>
  );
}
