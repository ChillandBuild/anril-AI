"use client";

import { useState } from "react";
import useSWR from "swr";
import { Copy } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useDltList } from "./DltForms";
import { isPeTmProof, peTmDate, peTmState } from "./dltSetup";
import { ENTITY_ID_MESSAGE, errorStatus, errorText, formatIst, friendlyError, isValidEntityId } from "./helpers";
import { useSms } from "./SmsShell";
import { Badge, Btn, Card, CardHeader, Empty, Field, LoadError, Notice, Skeleton, TableWrap, inputCls, tdCls, thCls } from "./ui";
import { usePerm } from "./usePerm";

const PETM_KEY = "sms:pe-tm";

function CopyValue({ label, value }: { label: string; value: string }) {
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(`${label} copied.`);
    } catch {
      toast.error("Couldn't copy. Select the text and copy it by hand.");
    }
  }
  return (
    <span className="mt-1 flex flex-wrap items-center gap-2">
      <span className="text-xs font-bold uppercase tracking-wider text-[#64748b]">{label}</span>
      <code className="rounded-lg bg-[#f1f5f9] px-2 py-1 text-sm font-semibold text-[#0A1528] break-all">{value || "—"}</code>
      <Btn variant="outline" className="h-8 px-3 text-xs" disabled={!value} onClick={() => void copy()}>
        <Copy size={12} /> Copy
      </Btn>
    </span>
  );
}

export function PeTmTab() {
  const { canManage } = usePerm();
  const { status, reloadStatus } = useSms();
  const tm = status.pe_tm_info;
  const dlt = useDltList();
  const { data, error, isLoading, mutate } = useSWR(PETM_KEY, () => api.sms.peTm(), { revalidateOnFocus: false });
  const [entityId, setEntityId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0);
  const [fileError, setFileError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);

  const items = data?.items ?? [];
  const entities = dlt.data?.entities ?? [];
  const unknownEntity = isValidEntityId(entityId) && !!dlt.data && !entities.some((e) => e.entity_id === entityId.trim());
  const nameFor = (id: string) => entities.find((e) => e.entity_id === id)?.entity_name ?? null;

  function onFile(f: File | null) {
    if (f && !isPeTmProof(f.name)) {
      setFile(null);
      return setFileError("Use a jpg, jpeg, png or pdf file.");
    }
    setFileError("");
    setFile(f);
  }

  async function upload() {
    if (uploading || !file || !entityId.trim()) return;
    if (!isValidEntityId(entityId)) {
      setUploadError(ENTITY_ID_MESSAGE);
      return;
    }
    setUploading(true);
    setUploadError("");
    try {
      await api.sms.peTmUpload(entityId.trim(), file);
      toast.success("Screenshot sent. We'll check it and approve the TM side.");
      setEntityId("");
      setFile(null);
      setFileKey((k) => k + 1);
      await mutate();
    } catch (err) {
      const code = errorStatus(err);
      if (code === 409) setUploadError("This entity's PE-TM binding is already done.");
      else setUploadError(friendlyError(err, "Couldn't upload the screenshot."));
    } finally {
      setUploading(false);
    }
  }

  async function confirm(id: string) {
    if (confirming) return;
    setConfirming(id);
    try {
      await api.sms.peTmConfirm(id);
      toast.success("Thanks. Final approval recorded.");
      await mutate();
      reloadStatus();
    } catch (err) {
      toast.error(errorStatus(err) === 409 ? "Wait until the TM side is approved, then try again." : errorText(err, "Couldn't record the final approval"));
      void mutate();
    } finally {
      setConfirming(null);
    }
  }

  return (
    <div className="space-y-4">
      {status.checklist.pe_tm && <Notice tone="success">PE-TM binding done — sending is on.</Notice>}

      <Card>
        <CardHeader title="Bind your entity to our telemarketer" hint="Four steps. Do them once for each entity." />
        <ol className="space-y-4 p-4 text-sm text-[#334155] sm:p-5">
          <li className="flex gap-3">
            <Step n={1} />
            <span>Log in to your DLT portal.</span>
          </li>
          <li className="flex gap-3">
            <Step n={2} />
            <span className="min-w-0">
              Add the TM (telemarketer) with this name and TM ID.
              <CopyValue label="TM name" value={tm.tm_name} />
              <CopyValue label="TM ID" value={tm.tm_id} />
            </span>
          </li>
          <li className="flex gap-3">
            <Step n={3} />
            <span>Raise the binding request for your entity and take a screenshot.</span>
          </li>
          <li className="flex gap-3">
            <Step n={4} />
            <span>Upload the screenshot below. After your account manager approves the TM side, approve it in your DLT portal and press {"“I’ve done the final approval”"}.</span>
          </li>
        </ol>
      </Card>

      {canManage && (
        <Card>
          <CardHeader title="Upload your screenshot" hint="jpg, jpeg, png or pdf." />
          <div className="space-y-3 p-4 sm:p-5">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Entity ID" hint="Pick one of your entities or type its ID.">
                <input className={inputCls} list="sms-petm-entities" value={entityId} onChange={(e) => setEntityId(e.target.value)} />
                <datalist id="sms-petm-entities">
                  {entities.map((e) => (
                    <option key={e.entity_id} value={e.entity_id}>
                      {e.entity_name ?? ""}
                    </option>
                  ))}
                </datalist>
              </Field>
              <Field label="Screenshot of the binding request">
                <input key={fileKey} type="file" accept=".jpg,.jpeg,.png,.pdf" className="block w-full text-sm" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
              </Field>
            </div>
            {fileError && <p className="text-xs font-semibold text-danger">{fileError}</p>}
            {unknownEntity && <p className="text-xs font-semibold text-[#b45309]">This ID isn&apos;t in your DLT Manager yet — check it&apos;s right.</p>}
            {uploadError && <Notice tone="danger">{uploadError}</Notice>}
            <Btn busy={uploading} disabled={!entityId.trim() || !file} onClick={() => void upload()}>
              Upload screenshot
            </Btn>
          </div>
        </Card>
      )}

      <Card>
        <CardHeader title="Your bindings" />
        {isLoading && !data ? (
          <div className="p-4 sm:p-5">
            <Skeleton className="h-24" />
          </div>
        ) : error && !data ? (
          <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
        ) : items.length === 0 ? (
          <Empty title="No bindings yet." hint="Upload your first screenshot above." />
        ) : (
          <TableWrap>
            <table className="w-full min-w-[40rem]">
              <thead>
                <tr className="border-b border-[#e2e8f0]">
                  <th className={thCls}>Entity</th>
                  <th className={thCls}>TM Approval</th>
                  <th className={thCls}>Final PE Confirmation</th>
                  <th className={thCls}>Date</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => {
                  const st = peTmState(it);
                  const name = nameFor(it.entity_id);
                  return (
                    <tr key={it.id} className="border-b border-[#f1f5f9] last:border-0">
                      <td className={tdCls}>
                        {name && <div>{name}</div>}
                        <div className="font-mono text-xs text-[#64748b]">{it.entity_id}</div>
                      </td>
                      <td className={tdCls}>
                        <Badge tone={st.tmApproved ? "success" : "warn"}>{st.tmApproved ? "Approved" : "Pending"}</Badge>
                      </td>
                      <td className={tdCls}>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge tone={st.done ? "success" : "warn"}>{st.done ? "Done" : "Pending"}</Badge>
                          {canManage && !st.done && (
                            <Btn className="h-8 px-3 text-xs" busy={confirming === it.id} disabled={!st.canConfirm} onClick={() => void confirm(it.id)}>
                              I&apos;ve done the final approval
                            </Btn>
                          )}
                        </div>
                      </td>
                      <td className={cn(tdCls, "whitespace-nowrap")}>{formatIst(peTmDate(it))}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>
    </div>
  );
}

function Step({ n }: { n: number }) {
  return <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-xs font-bold text-primary">{n}</span>;
}
