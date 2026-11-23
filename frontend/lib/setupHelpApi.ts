import { apiFetch } from "@/lib/api";
import { operatorFetch } from "@/lib/operator";

/** v9.2 #80: "Let the Anril team do it" on the first setup catalogue step, and the operator's list of those asks. */

export type SetupHelpStatus = { requested: boolean; requested_at: string | null };

export const setupHelpApi = {
  catalogueStatus: () => apiFetch<SetupHelpStatus>("/api/v1/setup-help/catalogue"),
  requestCatalogue: () => apiFetch<SetupHelpStatus>("/api/v1/setup-help/catalogue", { method: "POST" }),
};

export type OperatorSetupHelpRequest = {
  id: string;
  kind: string;
  status: string;
  created_at: string;
  tenant_id: string;
  tenant_name: string | null;
};

export const getOperatorSetupHelpRequests = () =>
  operatorFetch<{ items: OperatorSetupHelpRequest[] }>("/api/v1/operator/setup-help-requests");

export const finishOperatorSetupHelpRequest = (id: string, status: "done" | "cancelled") =>
  operatorFetch<{ ok: boolean }>(`/api/v1/operator/setup-help-requests/${encodeURIComponent(id)}/done`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
