"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Check, FolderPlus, X } from "lucide-react";
import { api, CustomerGroup } from "@/lib/api";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { ConfirmModal } from "@/components/ConfirmModal";
import { MobileRecordCard, MobileRecordField, MobileRecordGrid, MobileRecordHeader } from "@/components/MobileRecord";
import { cn } from "@/lib/utils";

const KIND_LABELS: Record<CustomerGroup["kind"], string> = {
  picked: "Picked by hand",
  rule: "Fills itself",
};

function formatCreated(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata" });
}

export function GroupsPanel() {
  const router = useRouter();
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("leads.manage");

  const [groups, setGroups] = useState<CustomerGroup[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleting, setDeleting] = useState<CustomerGroup | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const loadGroups = useCallback(async () => {
    try {
      setGroups(await api.customerGroups.list());
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
  }, []);

  useEffect(() => {
    loadGroups();
  }, [loadGroups]);

  async function createGroup() {
    const name = newName.trim();
    if (!name) return;
    setSaving(true);
    try {
      await api.customerGroups.create(name);
      toast.success(`Created ${name}`);
      setNewName("");
      setCreating(false);
      await loadGroups();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create group");
    } finally {
      setSaving(false);
    }
  }

  async function renameGroup(group: CustomerGroup) {
    const name = renameValue.trim();
    if (!name || name === group.name) {
      setRenamingId(null);
      return;
    }
    try {
      await api.customerGroups.rename(group.id, name);
      setRenamingId(null);
      await loadGroups();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not rename group");
    }
  }

  async function deleteGroup() {
    if (!deleting) return;
    setDeleteBusy(true);
    try {
      await api.customerGroups.remove(deleting.id);
      toast.success(`Deleted ${deleting.name}`);
      setDeleting(null);
      await loadGroups();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete group");
    } finally {
      setDeleteBusy(false);
    }
  }

  function startRename(group: CustomerGroup) {
    setRenamingId(group.id);
    setRenameValue(group.name);
  }

  const newGroupButton = canManage && (
    <button
      type="button"
      onClick={() => setCreating(true)}
      className="flex shrink-0 items-center gap-1.5 rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-primary-dark transition-colors"
    >
      <FolderPlus size={14} />
      New group
    </button>
  );

  const createRow = creating && canManage && (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        createGroup();
      }}
      className="flex flex-wrap items-center gap-2 border-b border-[#e2e8f0] p-4"
    >
      <input
        autoFocus
        value={newName}
        onChange={(e) => setNewName(e.target.value)}
        placeholder="Group name, e.g. Wedding clients"
        className="min-w-0 flex-1 rounded-xl border border-[#e2e8f0] px-3 py-2 text-xs text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20"
      />
      <button
        type="submit"
        disabled={saving || !newName.trim()}
        className="rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-white disabled:opacity-40"
      >
        Create
      </button>
      <button
        type="button"
        onClick={() => {
          setCreating(false);
          setNewName("");
        }}
        className="rounded-xl px-3 py-2 text-xs font-bold text-[#64748b] hover:text-[#0A1528]"
      >
        Cancel
      </button>
    </form>
  );

  function renderActions(group: CustomerGroup) {
    return (
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={() => router.push(`/dashboard/leads?tab=people&group_id=${group.id}`)}
          className="rounded-lg border border-primary px-3 py-1.5 text-xs font-bold text-primary hover:bg-primary/5"
        >
          Open
        </button>
        {canManage && (
          <>
            <button
              type="button"
              onClick={() => startRename(group)}
              className="rounded-lg px-2 py-1.5 text-xs font-bold text-[#0A1528] hover:bg-slate-50"
            >
              Rename
            </button>
            <button
              type="button"
              onClick={() => setDeleting(group)}
              className="rounded-lg px-2 py-1.5 text-xs font-bold text-danger hover:bg-danger/5"
            >
              Delete
            </button>
          </>
        )}
      </div>
    );
  }

  function renderRenameInput(group: CustomerGroup) {
    return (
      <form
        onSubmit={(e) => {
          e.preventDefault();
          renameGroup(group);
        }}
        className="flex items-center gap-1.5"
      >
        <input
          autoFocus
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setRenamingId(null);
          }}
          className="min-w-0 flex-1 rounded-lg border border-primary px-2.5 py-1.5 text-sm text-[#0A1528] focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <button type="submit" aria-label="Save name" className="rounded-lg p-1.5 text-primary hover:bg-primary/5">
          <Check size={14} />
        </button>
        <button
          type="button"
          onClick={() => setRenamingId(null)}
          aria-label="Cancel rename"
          className="rounded-lg p-1.5 text-[#64748b] hover:bg-slate-50"
        >
          <X size={14} />
        </button>
      </form>
    );
  }

  const isEmpty = groups !== null && groups.length === 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h2 className="font-display text-lg font-bold text-[#0A1528]">Groups</h2>
          <p className="mt-0.5 text-xs text-[#64748b]">
            Saved lists of people. Tick people in All people and press Add to group.
          </p>
        </div>
        {newGroupButton}
      </div>

      <div className="rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
        {createRow}

        {groups === null && !loadFailed && <div className="p-8 text-center text-xs text-[#64748b]">Loading...</div>}

        {loadFailed && (
          <div className="p-8 text-center text-xs text-[#64748b]">
            <p>Could not load your groups.</p>
            <button type="button" onClick={loadGroups} className="mt-2 text-xs font-semibold text-primary hover:opacity-70">
              Try again
            </button>
          </div>
        )}

        {isEmpty && (
          <div className="px-6 py-12 text-center">
            <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-primary/10 text-primary">
              <FolderPlus size={20} />
            </div>
            <h3 className="mt-4 font-display text-lg font-bold text-[#0A1528]">No groups yet</h3>
            <p className="mx-auto mt-1 max-w-md text-sm text-[#64748b]">
              Make a group to keep a list of people you want to message or call together.
            </p>
            {canManage && <div className="mt-5 flex justify-center">{newGroupButton}</div>}
          </div>
        )}

        {groups && groups.length > 0 && (
          <>
            {/* Desktop table */}
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-[#f1f5f9]">
                    <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">Name</th>
                    <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">People</th>
                    <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">Type</th>
                    <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">Created</th>
                    <th className="px-4 py-3 text-right text-[10px] font-bold uppercase tracking-wider text-[#64748b]">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((group) => (
                    <tr key={group.id} className="border-t border-[#f1f5f9] hover:bg-[#f8fafc] transition-colors">
                      <td className="px-4 py-3">
                        {renamingId === group.id ? (
                          renderRenameInput(group)
                        ) : (
                          <span className="font-bold text-sm text-[#0A1528]">{group.name}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-[#334155]">{group.member_count.toLocaleString("en-IN")}</td>
                      <td className="px-4 py-3 text-xs text-[#64748b]">{KIND_LABELS[group.kind]}</td>
                      <td className="px-4 py-3 text-xs text-[#64748b]">{formatCreated(group.created_at)}</td>
                      <td className="px-4 py-3">{renderActions(group)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Phone cards */}
            <div className="block space-y-3 p-3 md:hidden">
              {groups.map((group) => (
                <MobileRecordCard key={group.id}>
                  {renamingId === group.id ? (
                    renderRenameInput(group)
                  ) : (
                    <MobileRecordHeader title={group.name} subtitle={KIND_LABELS[group.kind]} />
                  )}
                  <MobileRecordGrid>
                    <MobileRecordField label="People" value={group.member_count.toLocaleString("en-IN")} />
                    <MobileRecordField label="Created" value={formatCreated(group.created_at)} />
                  </MobileRecordGrid>
                  <div className={cn("mt-4", renamingId === group.id && "hidden")}>{renderActions(group)}</div>
                </MobileRecordCard>
              ))}
            </div>
          </>
        )}
      </div>

      <ConfirmModal
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={deleteGroup}
        title="Delete this group?"
        description={`This removes "${deleting?.name ?? ""}". The people in it are not deleted.`}
        tone="danger"
        confirmLabel="Delete group"
        loading={deleteBusy}
        loadingLabel="Deleting…"
      />
    </div>
  );
}
