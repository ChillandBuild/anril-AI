"use client";

import { useState } from "react";
import useSWR from "swr";
import { Download, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, type SmsContactGroup } from "@/lib/api";
import { formatCount, formatIst, friendlyError } from "./helpers";
import { Btn, Card, CardHeader, Empty, LoadError, Modal, Notice, Skeleton, inputCls } from "./ui";
import { usePerm } from "./usePerm";

export function GroupsPanel() {
  const { canManage } = usePerm();
  const groups = useSWR("sms:contact-groups", () => api.sms.contactGroups(), { revalidateOnFocus: false });
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<SmsContactGroup | null>(null);
  const [deleteBusy, setDeleteBusy] = useState<"group" | "contacts" | null>(null);
  const [exportingId, setExportingId] = useState<string | null>(null);

  const list = groups.data?.groups ?? [];

  async function exportCsv(g: SmsContactGroup) {
    setExportingId(g.id);
    try {
      await api.sms.exportGroupCsv(g.id, g.name);
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't export the group."));
    } finally {
      setExportingId(null);
    }
  }

  async function create() {
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    setCreateError(null);
    try {
      await api.sms.createContactGroup(name);
      setNewName("");
      await groups.mutate();
    } catch (err) {
      setCreateError(friendlyError(err, "Couldn't create the group."));
    } finally {
      setCreating(false);
    }
  }

  async function rename() {
    if (!editing || !editing.name.trim()) return;
    setRenaming(true);
    setRenameError(null);
    try {
      await api.sms.renameContactGroup(editing.id, editing.name.trim());
      setEditing(null);
      await groups.mutate();
    } catch (err) {
      setRenameError(friendlyError(err, "Couldn't rename the group."));
    } finally {
      setRenaming(false);
    }
  }

  async function remove(withContacts: boolean) {
    if (!deleting) return;
    setDeleteBusy(withContacts ? "contacts" : "group");
    try {
      const res = await api.sms.deleteContactGroup(deleting.id, withContacts);
      toast.success(withContacts ? `Group deleted with ${formatCount(res.deleted_contacts)} contact(s).` : "Group deleted. Contacts kept.");
      setDeleting(null);
      await groups.mutate();
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't delete the group."));
    } finally {
      setDeleteBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader title="Groups" hint="Put contacts in groups, then pick a group when you send a campaign." />
      {canManage && (
        <form
          className="flex flex-wrap items-end gap-2 border-b border-[#f1f5f9] px-4 py-3 sm:px-5"
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
        >
          <input aria-label="New group name" className={`${inputCls} min-w-[200px] flex-1 sm:max-w-xs`} placeholder="New group name" maxLength={80} value={newName} onChange={(e) => setNewName(e.target.value)} />
          <Btn type="submit" busy={creating} disabled={!newName.trim()}>
            <Plus size={15} /> Add group
          </Btn>
          {createError && <p className="w-full text-xs font-semibold text-danger">{createError}</p>}
        </form>
      )}
      {groups.isLoading && !groups.data ? (
        <Skeleton className="m-4 h-32" />
      ) : groups.error && !groups.data ? (
        <LoadError message={friendlyError(groups.error, "Check your connection.")} onRetry={() => void groups.mutate()} />
      ) : list.length === 0 ? (
        <Empty title="No groups yet." hint={canManage ? "Create one above, or name a group while uploading contacts." : undefined} />
      ) : (
        <ul className="divide-y divide-[#f1f5f9]">
          {list.map((g) => (
            <li key={g.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 sm:px-5">
              {editing?.id === g.id ? (
                <form
                  className="flex min-w-0 flex-1 flex-wrap items-center gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void rename();
                  }}
                >
                  <input aria-label="Group name" className={`${inputCls} min-w-[180px] flex-1 sm:max-w-xs`} maxLength={80} value={editing.name} onChange={(e) => setEditing({ id: g.id, name: e.target.value })} />
                  <Btn type="submit" busy={renaming} disabled={!editing.name.trim()} className="h-9">
                    Save
                  </Btn>
                  <Btn variant="outline" className="h-9" disabled={renaming} onClick={() => setEditing(null)}>
                    Cancel
                  </Btn>
                  {renameError && <p className="w-full text-xs font-semibold text-danger">{renameError}</p>}
                </form>
              ) : (
                <>
                  <div className="min-w-0">
                    <p className="break-words text-sm font-bold text-[#0A1528]">{g.name}</p>
                    <p className="text-xs text-[#64748b]">
                      {formatCount(g.contacts)} contact{g.contacts === 1 ? "" : "s"} · created {formatIst(g.created_at)}
                    </p>
                  </div>
                  {canManage && (
                    <div className="flex gap-2">
                      <Btn
                        variant="outline"
                        className="h-9"
                        aria-label={`Export ${g.name}`}
                        busy={exportingId === g.id}
                        disabled={exportingId !== null}
                        onClick={() => void exportCsv(g)}
                      >
                        {exportingId === g.id ? "Exporting…" : <><Download size={14} /> Export</>}
                      </Btn>
                      <Btn
                        variant="outline"
                        className="h-9"
                        aria-label={`Rename ${g.name}`}
                        onClick={() => {
                          setRenameError(null);
                          setEditing({ id: g.id, name: g.name });
                        }}
                      >
                        <Pencil size={14} /> Rename
                      </Btn>
                      <Btn variant="danger" className="h-9" aria-label={`Delete ${g.name}`} onClick={() => setDeleting(g)}>
                        <Trash2 size={14} /> Delete
                      </Btn>
                    </div>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      <Modal open={!!deleting} title={`Delete “${deleting?.name ?? ""}”?`} onClose={() => !deleteBusy && setDeleting(null)}>
        <div className="space-y-3">
          <Notice tone="warn">Pick what happens to the {formatCount(deleting?.contacts ?? 0)} contact(s) in this group. Deleting can&apos;t be undone.</Notice>
          <Btn variant="outline" className="h-auto w-full whitespace-normal py-2.5" busy={deleteBusy === "group"} disabled={!!deleteBusy} onClick={() => void remove(false)}>
            Delete group only (keep contacts)
          </Btn>
          <Btn variant="danger" className="h-auto w-full whitespace-normal py-2.5" busy={deleteBusy === "contacts"} disabled={!!deleteBusy} onClick={() => void remove(true)}>
            Delete group and contacts that are only in this group
          </Btn>
          <Btn variant="link" className="w-full" disabled={!!deleteBusy} onClick={() => setDeleting(null)}>
            Cancel
          </Btn>
        </div>
      </Modal>
    </Card>
  );
}
