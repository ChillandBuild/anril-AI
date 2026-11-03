"use client";

import { TemplateList } from "./TemplateList";
import { TemplateRequests } from "./TemplateRequests";
import { Notice } from "./ui";

/** DLT Manager > Content Template: the list (with Add / Import / Refresh) and the request-a-template form. */
export function TemplatesTab() {
  return (
    <div className="space-y-4">
      <Notice tone="info">New templates are approved on your DLT portal (Jio, Airtel, Vi). Once approved, add them here.</Notice>
      <TemplateList />
      <TemplateRequests />
    </div>
  );
}
