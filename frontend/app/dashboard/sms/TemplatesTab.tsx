"use client";

import { mutate as globalMutate } from "swr";
import { DltForms } from "./DltForms";
import { TemplateList } from "./TemplateList";
import { TemplateRequests } from "./TemplateRequests";
import { Notice } from "./ui";
import { usePerm } from "./usePerm";

export function TemplatesTab() {
  const { canManage } = usePerm();
  return (
    <div className="space-y-4">
      <Notice tone="info">New templates are approved on your DLT portal (Jio, Airtel, Vi). Once approved, add them here.</Notice>
      <TemplateList />
      {canManage && <DltForms onChanged={() => void globalMutate("sms:templates")} />}
      <TemplateRequests />
    </div>
  );
}
