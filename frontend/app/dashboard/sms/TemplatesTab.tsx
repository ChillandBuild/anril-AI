"use client";

import { TemplateList } from "./TemplateList";
import { Notice } from "./ui";

/** DLT Manager > Content Template: the list (with Add / Import / Refresh). */
export function TemplatesTab() {
  return (
    <div className="space-y-4">
      <Notice tone="info">New templates are approved on your DLT portal (Jio, Airtel, Vi). Once approved, add them here.</Notice>
      <TemplateList />
    </div>
  );
}
