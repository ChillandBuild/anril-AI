"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  CheckCircle2,
  Copy,
  Crown,
  Download,
  Eye,
  EyeOff,
  Folder,
  Inbox,
  KeyRound,
  Loader2,
  Mail,
  Pencil,
  Phone,
  Plus,
  RotateCcw,
  Search,
  ShieldCheck,
  Smartphone,
  Trash2,
  User,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { api, API_URL, AuditLogEntry, ClientRole, PermissionDef, RbacUser } from "@/lib/api";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { cn } from "@/lib/utils";
import { ConfirmModal } from "@/components/ConfirmModal";
import { CheckTick } from "@/components/ui/controls";

type Tab = "roles" | "users" | "audit";
type CallingProvider = "telecmi" | "sim_basic";

type ConfirmState = {
  title: string;
  description: string;
  tone: "danger" | "warning" | "primary";
  confirmLabel?: string;
  onConfirm: () => void;
};

const AIRA_SYNC_APK_URL = "https://ayftynkgmfkaqmmnlmoc.supabase.co/storage/v1/object/public/app-releases/aira-sync.apk";

type AccessModule = {
  id: string;
  title: string;
  description: string;
  group: string;
  readKeys: string[];
  writeKeys: string[];
};

const ACCESS_MODULES: AccessModule[] = [
  { id: "dashboard", title: "Dashboard", description: "View executive metrics and workspace status.", group: "Overview", readKeys: ["dashboard.view"], writeKeys: [] },
  { id: "conversations", title: "Conversations", description: "Open inbox threads and reply to customers.", group: "Messaging", readKeys: ["conversations.view"], writeKeys: ["conversations.reply"] },
  { id: "segments", title: "Segments", description: "View and update lead segments.", group: "Leads", readKeys: ["leads.view"], writeKeys: ["leads.manage"] },
  { id: "inbound", title: "Inbound Leads", description: "Review inbound enquiries and handoffs.", group: "Leads", readKeys: ["inbound_leads.view"], writeKeys: ["inbound_leads.manage"] },
  { id: "deals", title: "Deals", description: "Track the sales pipeline and move deals between stages.", group: "Leads", readKeys: ["deals.view"], writeKeys: ["deals.manage"] },
  { id: "meta_ads", title: "Meta Ads", description: "See ad performance and create ad tracking links.", group: "Leads", readKeys: ["meta_ads.view"], writeKeys: ["meta_ads.manage"] },
  { id: "outbound", title: "Outbound Leads", description: "Review outbound batches and campaign history.", group: "Messaging", readKeys: ["outbound_leads.view"], writeKeys: ["outbound_leads.manage"] },
  { id: "templates", title: "Templates", description: "Review and manage WhatsApp templates.", group: "Messaging", readKeys: ["templates.view"], writeKeys: ["templates.manage"] },
  { id: "numbers", title: "Numbers Pool", description: "Review and manage sender numbers.", group: "Messaging", readKeys: ["numbers.view"], writeKeys: ["numbers.manage"] },
  { id: "auto_messages", title: "Auto-Messages", description: "Review automatic messages or edit rules and send from the shop counter.", group: "Messaging", readKeys: ["auto_messages.view"], writeKeys: ["auto_messages.manage"] },
  { id: "knowledge", title: "Knowledge Base", description: "Review and maintain AI answer sources.", group: "AI", readKeys: ["knowledge.view"], writeKeys: ["knowledge.manage"] },
  { id: "brain", title: "Anril Brain", description: "See what Anril has learned. Edits here follow Knowledge Base write access.", group: "AI", readKeys: ["brain.view"], writeKeys: [] },
  { id: "catalog", title: "Catalog", description: "Review and maintain product and service items.", group: "AI", readKeys: ["catalog.view"], writeKeys: ["catalog.manage"] },
  { id: "services", title: "Services", description: "Review or edit service packages and pricing.", group: "AI", readKeys: ["services.view"], writeKeys: ["services.manage"] },
  { id: "analytics", title: "Analytics", description: "View campaign, funnel, and performance reports.", group: "Reports", readKeys: ["analytics.view"], writeKeys: [] },
  { id: "subscription", title: "Subscription", description: "Review and update subscription controls.", group: "Admin", readKeys: ["subscription.view"], writeKeys: ["subscription.manage"] },
  { id: "team", title: "Team", description: "View performance and manage caller operations.", group: "Team", readKeys: ["team.view"], writeKeys: ["team.manage"] },
  { id: "roles", title: "Roles", description: "Review roles or manage user access.", group: "Admin", readKeys: ["roles.view"], writeKeys: ["roles.manage"] },
  { id: "settings", title: "Settings", description: "Review or configure workspace settings.", group: "Admin", readKeys: ["settings.view"], writeKeys: ["settings.manage"] },
  { id: "dialer", title: "Telecalling Dialer", description: "View or use the calling cockpit.", group: "Telecalling", readKeys: ["telecalling.dialer.view"], writeKeys: ["telecalling.dialer"] },
  { id: "upload", title: "Telecalling Upload", description: "View or upload call lists and batches.", group: "Telecalling", readKeys: ["telecalling.upload.view"], writeKeys: ["telecalling.upload"] },
  { id: "scheduled", title: "Scheduled Calls", description: "View or work callback queues.", group: "Telecalling", readKeys: ["telecalling.scheduled.view"], writeKeys: ["telecalling.scheduled"] },
  { id: "notes", title: "Call Notes", description: "Read or write call notes.", group: "Telecalling", readKeys: ["telecalling.notes.view"], writeKeys: ["telecalling.notes"] },
];

const emptyRole = { name: "", permissions: [] as string[] };
const emptyUser = {
  full_name: "",
  email: "",
  role_id: "",
  temporary_password: "",
  phone: "",
  telecmi_agent_id: "",
  telecmi_agent_password: "",
};

function makePassword() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
  const body = Array.from({ length: 13 }, () => chars[Math.floor(Math.random() * chars.length)]).join("");
  return `${body}9!`;
}

function unique(values: string[]) {
  return Array.from(new Set(values));
}

function hasAnyPermission(rolePermissions: string[], keys: string[]) {
  return keys.some((key) => rolePermissions.includes(key));
}

function moduleActiveCount(rolePermissions: string[]) {
  return ACCESS_MODULES.filter((module) =>
    hasAnyPermission(rolePermissions, [...module.readKeys, ...module.writeKeys]),
  ).length;
}

function providerLabel(provider: CallingProvider) {
  return provider === "sim_basic" ? "SIM Basic" : "Cloud Telephony";
}

function groupModules(modules: AccessModule[]) {
  const groups: { name: string; modules: AccessModule[] }[] = [];
  const byName = new Map<string, AccessModule[]>();
  for (const mod of modules) {
    if (!byName.has(mod.group)) {
      byName.set(mod.group, []);
      groups.push({ name: mod.group, modules: byName.get(mod.group)! });
    }
    byName.get(mod.group)!.push(mod);
  }
  return groups;
}

// Hides 6 characters of the account segment, keeping the agent extension (the
// part that differs per user) readable.
const MASKED_CHARS = 6;

function maskAgentId(value: string) {
  const separator = value.indexOf("_");
  const prefix = separator < 0 ? "" : `${value.slice(0, separator)}_`;
  const account = separator < 0 ? value : value.slice(separator + 1);
  const hidden = Math.min(MASKED_CHARS, account.length);
  return `${prefix}${"•".repeat(hidden)}${account.slice(hidden)}`;
}

function ownerCallingReady(user: RbacUser, provider: CallingProvider) {
  const profile = user.caller_profile;
  if (!profile?.phone) return false;
  return provider !== "telecmi" || !!profile.telecmi_agent_id;
}

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

const AVATAR_PALETTE = [
  "bg-primary-100 text-primary-700",
  "bg-blue-100 text-blue-700",
  "bg-emerald-100 text-emerald-700",
  "bg-amber-100 text-amber-700",
  "bg-rose-100 text-rose-700",
  "bg-cyan-100 text-cyan-700",
];

function avatarColor(seed: string) {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[hash % AVATAR_PALETTE.length];
}

export default function RolesPage() {
  const { role, permissions: myPermissions, loading: roleLoading } = useAuthRole();
  const canWrite = role === "owner" || myPermissions.includes("roles.manage");
  const canView = canWrite || myPermissions.includes("roles.view");
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlTab: Tab = searchParams.get("tab") === "users" ? "users" : searchParams.get("tab") === "audit" ? "audit" : "roles";
  const [tab, setTab] = useState<Tab>(urlTab);
  const [roles, setRoles] = useState<ClientRole[]>([]);
  const [users, setUsers] = useState<RbacUser[]>([]);
  const [permissions, setPermissions] = useState<PermissionDef[]>([]);
  const [callingProvider, setCallingProvider] = useState<CallingProvider>("telecmi");
  const [telecallerSeats, setTelecallerSeats] = useState<{ limit: number; used: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [roleSearch, setRoleSearch] = useState("");
  const [roleDraft, setRoleDraft] = useState(emptyRole);
  const [editingRoleId, setEditingRoleId] = useState<string | null>(null);
  const [userDraft, setUserDraft] = useState(emptyUser);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  // The Master account is not editable through the RBAC user endpoints, but its
  // calling profile (phone + Cloud Telephony User ID) still has to live somewhere —
  // this mode edits the owner's `callers` row directly.
  const [editingOwner, setEditingOwner] = useState<{ callerId: string; name: string } | null>(null);
  const [temporaryPassword, setTemporaryPassword] = useState<{ label: string; value: string } | null>(null);
  const [showDraftPassword, setShowDraftPassword] = useState(false);
  const [showIssuedPassword, setShowIssuedPassword] = useState(true);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [syncToken, setSyncToken] = useState<{ label: string; value: string } | null>(null);
  const [showSyncToken, setShowSyncToken] = useState(true);
  const [mintingSyncToken, setMintingSyncToken] = useState<string | null>(null);
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [syncTokenDialogUser, setSyncTokenDialogUser] = useState<RbacUser | null>(null);
  const [viewingSyncToken, setViewingSyncToken] = useState<string | null>(null);
  const [auditEntries, setAuditEntries] = useState<AuditLogEntry[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [auditLoading, setAuditLoading] = useState(true); // the audit tab fetches as soon as it opens

  useEffect(() => {
    setTab(urlTab);
  }, [urlTab]);

  function setActiveTab(nextTab: Tab) {
    setTab(nextTab);
    const params = new URLSearchParams(searchParams.toString());
    if (nextTab === "users") params.set("tab", "users");
    else params.delete("tab");
    const query = params.toString();
    router.replace(`/dashboard/roles${query ? `?${query}` : ""}`, { scroll: false });
  }

  const catalogKeys = useMemo(() => new Set(permissions.map((permission) => permission.key)), [permissions]);
  const availableModules = useMemo(() => {
    if (catalogKeys.size === 0) return ACCESS_MODULES;
    return ACCESS_MODULES.filter((module) =>
      [...module.readKeys, ...module.writeKeys].some((key) => catalogKeys.has(key)),
    );
  }, [catalogKeys]);
  const moduleGroups = useMemo(() => groupModules(availableModules), [availableModules]);

  const roleById = useMemo(() => new Map(roles.map((r) => [r.id, r])), [roles]);
  const selectedRole = roleById.get(userDraft.role_id);
  const selectedRoleIsTelecaller = selectedRole?.is_telecaller ?? (selectedRole?.slug === "telecaller" || selectedRole?.permissions.includes("telecalling.dialer"));
  const editingRole = editingRoleId ? roleById.get(editingRoleId) : null;
  const editingUser = editingUserId ? users.find((u) => u.user_id === editingUserId) : null;
  const alreadyActiveTelecaller = !!editingUser?.caller_profile?.active;
  // Only a NEW telecaller enrollment consumes a seat -- editing a user who's
  // already an active telecaller (e.g. changing their name) must not be blocked.
  const wouldConsumeSeat = selectedRoleIsTelecaller && !alreadyActiveTelecaller;
  const atSeatLimit = wouldConsumeSeat && !!telecallerSeats && telecallerSeats.used >= telecallerSeats.limit;

  const filteredRoles = useMemo(() => {
    const query = roleSearch.trim().toLowerCase();
    if (!query) return roles;
    return roles.filter((item) => item.name.toLowerCase().includes(query) || (item.slug ?? "").toLowerCase().includes(query));
  }, [roleSearch, roles]);

  async function load() {
    setError(null);
    setLoading(true);
    try {
      const [roleRes, userRes, assignmentRes] = await Promise.all([
        api.rbac.roles(),
        api.rbac.users(),
        api.calls.assignmentMode().catch(() => null),
      ]);
      setRoles(roleRes.data);
      setPermissions(roleRes.permissions);
      setUsers(userRes.data);
      setTelecallerSeats(userRes.telecaller_seats ?? null);
      setCallingProvider(assignmentRes?.calling_provider ?? "telecmi");
      if (roleRes.setup_required) {
        setError(roleRes.detail ?? "RBAC setup is not complete yet.");
      }
      setUserDraft((d) => ({
        ...d,
        role_id: d.role_id || roleRes.data.find((r) => r.slug === "telecaller")?.id || roleRes.data[0]?.id || "",
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load roles");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!roleLoading && canView) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roleLoading, canView]);

  useEffect(() => {
    if (tab !== "audit" || !canView) return;
    let active = true;
    setAuditLoading(true);
    api.rbac.auditLog({ page: auditPage }).then((res) => {
      if (!active) return;
      setAuditEntries(res.data);
      setAuditTotal(res.total);
    }).catch(() => undefined).finally(() => {
      if (active) setAuditLoading(false);
    });
    return () => { active = false; };
  }, [tab, auditPage, canView]);

  function startRole(role: ClientRole) {
    setEditingRoleId(role.id);
    setRoleDraft({
      name: role.name,
      permissions: role.permissions,
    });
    setActiveTab("roles");
  }

  function resetRole() {
    setEditingRoleId(null);
    setRoleDraft(emptyRole);
  }

  function startUser(user: RbacUser) {
    setEditingUserId(user.user_id);
    setEditingOwner(null);
    setUserDraft({
      ...emptyUser,
      full_name: user.full_name,
      email: user.email,
      role_id: user.role_id || roles.find((r) => r.slug === "telecaller")?.id || "",
      phone: user.caller_profile?.phone ?? "",
      telecmi_agent_id: user.caller_profile?.telecmi_agent_id ?? "",
    });
    setActiveTab("users");
  }

  function startOwnerCalling(user: RbacUser) {
    const callerId = user.caller_profile?.id;
    if (!callerId) return;
    setEditingUserId(null);
    setEditingOwner({ callerId, name: user.full_name || user.email });
    setUserDraft({
      ...emptyUser,
      full_name: user.full_name,
      email: user.email,
      phone: user.caller_profile?.phone ?? "",
      telecmi_agent_id: user.caller_profile?.telecmi_agent_id ?? "",
    });
    setActiveTab("users");
  }

  function resetUser() {
    setEditingUserId(null);
    setEditingOwner(null);
    setUserDraft({
      ...emptyUser,
      role_id: roles.find((r) => r.slug === "telecaller")?.id || roles[0]?.id || "",
      temporary_password: makePassword(),
    });
  }

  useEffect(() => {
    if (!userDraft.temporary_password && !editingUserId && !editingOwner) {
      setUserDraft((d) => ({ ...d, temporary_password: makePassword() }));
    }
  }, [editingUserId, editingOwner, userDraft.temporary_password]);

  function setModuleAccess(module: AccessModule, access: "read" | "write", checked: boolean) {
    setRoleDraft((draft) => {
      const current = new Set(draft.permissions);
      const readKeys = module.readKeys.filter((key) => catalogKeys.size === 0 || catalogKeys.has(key));
      const writeKeys = module.writeKeys.filter((key) => catalogKeys.size === 0 || catalogKeys.has(key));

      if (access === "read") {
        if (checked) {
          readKeys.forEach((key) => current.add(key));
        } else {
          [...readKeys, ...writeKeys].forEach((key) => current.delete(key));
        }
      } else if (checked) {
        [...readKeys, ...writeKeys].forEach((key) => current.add(key));
      } else {
        writeKeys.forEach((key) => current.delete(key));
      }

      return { ...draft, permissions: unique(Array.from(current)).sort() };
    });
  }

  function clearModule(module: AccessModule) {
    const keys = new Set([...module.readKeys, ...module.writeKeys]);
    setRoleDraft((draft) => ({ ...draft, permissions: draft.permissions.filter((key) => !keys.has(key)) }));
  }

  async function saveRole(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (editingRoleId) {
        await api.rbac.updateRole(editingRoleId, roleDraft);
      } else {
        await api.rbac.createRole(roleDraft);
      }
      resetRole();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save role");
    } finally {
      setSaving(false);
    }
  }

  async function saveUser(e: React.FormEvent) {
    e.preventDefault();
    if (atSeatLimit) return;
    setSaving(true);
    setError(null);
    try {
      if (editingOwner) {
        const patch: { phone?: string; telecmi_agent_id?: string | null } = {};
        const phone = userDraft.phone.trim();
        if (phone) patch.phone = phone;
        if (callingProvider === "telecmi") patch.telecmi_agent_id = userDraft.telecmi_agent_id.trim() || null;
        if (Object.keys(patch).length > 0) await api.callers.update(editingOwner.callerId, patch);
        resetUser();
        await load();
        return;
      }
      const payload = {
        ...userDraft,
        phone: selectedRoleIsTelecaller ? userDraft.phone.trim() || null : null,
        telecmi_agent_id: selectedRoleIsTelecaller && callingProvider === "telecmi" ? userDraft.telecmi_agent_id.trim() || null : null,
        telecmi_agent_password: null,
      };
      if (editingUserId) {
        await api.rbac.updateUser(editingUserId, payload);
      } else {
        const created = await api.rbac.createUser(payload);
        setTemporaryPassword({ label: userDraft.full_name || userDraft.email, value: created.temporary_password });
      }
      resetUser();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save user");
    } finally {
      setSaving(false);
    }
  }

  function resetPassword(user: RbacUser) {
    setConfirmState({
      title: "Reset password",
      description: `Issue a new temporary password for "${user.full_name || user.email}"? They'll be required to set a new password on next login.`,
      tone: "warning",
      confirmLabel: "Reset password",
      onConfirm: () => runResetPassword(user),
    });
  }

  async function runResetPassword(user: RbacUser) {
    setSaving(true);
    setError(null);
    try {
      const res = await api.rbac.resetPassword(user.user_id);
      setTemporaryPassword({ label: user.full_name || user.email, value: res.temporary_password });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reset password");
    } finally {
      setSaving(false);
      setConfirmState(null);
    }
  }

  function regenerateSyncToken(user: RbacUser) {
    const callerId = user.caller_profile?.id;
    if (!callerId) return;
    setSyncTokenDialogUser(null);
    setConfirmState({
      title: "Regenerate Anril Sync token",
      description: `Generate a new Anril Sync token for "${user.full_name || user.email}"? This immediately invalidates their current token — their Anril Sync app will stop syncing until you paste in the new one.`,
      tone: "danger",
      confirmLabel: "Regenerate",
      onConfirm: () => runRegenerateSyncToken(user, callerId),
    });
  }

  async function runRegenerateSyncToken(user: RbacUser, callerId: string) {
    setMintingSyncToken(callerId);
    setError(null);
    try {
      const res = await api.callers.generateSyncToken(callerId);
      setShowSyncToken(true);
      setSyncToken({ label: user.full_name || user.email, value: res.sync_token });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate sync token");
    } finally {
      setMintingSyncToken(null);
      setConfirmState(null);
    }
  }

  async function viewSyncToken(user: RbacUser) {
    const callerId = user.caller_profile?.id;
    if (!callerId) return;
    setViewingSyncToken(callerId);
    setError(null);
    try {
      const res = await api.callers.getSyncToken(callerId);
      setSyncTokenDialogUser(null);
      setShowSyncToken(true);
      setSyncToken({ label: user.full_name || user.email, value: res.sync_token });
    } catch (e) {
      setError(e instanceof Error ? e.message : "No sync token has been generated for this caller yet");
    } finally {
      setViewingSyncToken(null);
    }
  }

  function deleteRole(roleItem: ClientRole) {
    if (!canWrite) return;
    setConfirmState({
      title: "Delete role",
      description: `Delete role "${roleItem.name}"? This only works when no users are assigned to it.`,
      tone: "danger",
      confirmLabel: "Delete",
      onConfirm: () => runDeleteRole(roleItem),
    });
  }

  async function runDeleteRole(roleItem: ClientRole) {
    setDeleting(`role:${roleItem.id}`);
    setError(null);
    try {
      await api.rbac.deleteRole(roleItem.id);
      if (editingRoleId === roleItem.id) resetRole();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete role");
    } finally {
      setDeleting(null);
      setConfirmState(null);
    }
  }

  function deleteUser(user: RbacUser) {
    if (!canWrite) return;
    setConfirmState({
      title: "Delete user",
      description: `Delete user "${user.full_name || user.email}"? This permanently removes their access and caller profile — call history stays but loses attribution to them, and any leads currently assigned to them become unassigned.`,
      tone: "danger",
      confirmLabel: "Delete",
      onConfirm: () => runDeleteUser(user),
    });
  }

  async function runDeleteUser(user: RbacUser) {
    setDeleting(`user:${user.user_id}`);
    setError(null);
    try {
      await api.rbac.deleteUser(user.user_id);
      if (editingUserId === user.user_id) resetUser();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete user");
    } finally {
      setDeleting(null);
      setConfirmState(null);
    }
  }

  if (roleLoading || loading) {
    return <div className="flex min-h-[400px] items-center justify-center"><Loader2 size={24} className="animate-spin text-primary" /></div>;
  }

  if (!canView) {
    return <div className="py-20 text-center"><p className="font-body text-sm text-ink-muted">Only admins with role access can open this page.</p></div>;
  }

  return (
    <div className="min-w-0 space-y-6">
      {error && <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 font-body text-sm text-red-700">{error}</div>}

      {temporaryPassword && (
        <div className="flex flex-col gap-3 rounded-3xl border border-emerald-200 bg-emerald-50 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-label text-[10px] font-black uppercase tracking-wider text-emerald-700">Temporary password for {temporaryPassword.label}</p>
            <p className="mt-1 font-mono text-sm font-bold text-ink">{showIssuedPassword ? temporaryPassword.value : "••••••••••••••"}</p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-secondary justify-center px-3"
              onClick={() => setShowIssuedPassword((value) => !value)}
              title={showIssuedPassword ? "Hide password" : "Show password"}
            >
              {showIssuedPassword ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
            <button
              type="button"
              className="btn-secondary justify-center"
              onClick={() => navigator.clipboard?.writeText(temporaryPassword.value)}
            >
              <Copy size={14} /> Copy
            </button>
          </div>
        </div>
      )}

      {role === "owner" && callingProvider === "sim_basic" && (
        <div className="flex flex-col gap-3 rounded-3xl border border-border-subtle bg-white p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border-subtle bg-primary-50 text-primary-600">
              <Smartphone size={18} />
            </div>
            <div>
              <p className="font-body text-sm font-bold text-ink">Anril Sync — Android app</p>
              <p className="mt-0.5 font-body text-xs text-ink-muted">Not on Play Store — sideload this APK on each telecaller&apos;s phone for automatic call-log tracking.</p>
            </div>
          </div>
          <a
            href={AIRA_SYNC_APK_URL}
            download
            className="btn-secondary shrink-0 justify-center"
          >
            <Download size={14} /> Download APK
          </a>
        </div>
      )}

      {syncToken && (
        <div className="flex flex-col gap-3 rounded-3xl border border-primary-200 bg-primary-50 p-4">
          <p className="font-label text-[10px] font-black uppercase tracking-wider text-primary-700">Anril Sync setup for {syncToken.label}</p>
          <p className="font-body text-xs text-primary-700">Paste both fields into the Anril Sync app on the caller&apos;s phone, then tap Save &amp; Connect. The token is shown once.</p>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="font-label text-[9px] font-black uppercase tracking-wider text-ink-muted">Server URL</p>
              <p className="mt-0.5 break-all font-mono text-sm font-bold text-ink">{API_URL}</p>
            </div>
            <button
              type="button"
              className="btn-secondary shrink-0 justify-center"
              onClick={() => navigator.clipboard?.writeText(API_URL)}
            >
              <Copy size={14} /> Copy
            </button>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="font-label text-[9px] font-black uppercase tracking-wider text-ink-muted">Sync Token</p>
              <p className="mt-0.5 break-all font-mono text-sm font-bold text-ink">{showSyncToken ? syncToken.value : "••••••••••••••••••••••••••••••••"}</p>
            </div>
            <div className="flex shrink-0 gap-2">
              <button
                type="button"
                className="btn-secondary justify-center px-3"
                onClick={() => setShowSyncToken((value) => !value)}
                title={showSyncToken ? "Hide token" : "Show token"}
              >
                {showSyncToken ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
              <button
                type="button"
                className="btn-secondary justify-center"
                onClick={() => navigator.clipboard?.writeText(syncToken.value)}
              >
                <Copy size={14} /> Copy
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="card flex items-center gap-3 rounded-2xl border border-primary-100 bg-primary-50/50 p-4 shadow-sm">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border-subtle bg-white text-primary-600">
            <ShieldCheck size={18} />
          </div>
          <div className="min-w-0">
            <p className="font-body text-xs font-bold uppercase tracking-wider text-ink-muted">Roles Defined</p>
            <p className="mt-0.5 font-display text-lg font-black text-ink">{roles.length}</p>
          </div>
        </div>
        <div className="card flex items-center gap-3 rounded-2xl border border-blue-100 bg-blue-50/50 p-4 shadow-sm">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border-subtle bg-white text-blue-600">
            <Users size={18} />
          </div>
          <div className="min-w-0">
            <p className="font-body text-xs font-bold uppercase tracking-wider text-ink-muted">Total Users</p>
            <p className="mt-0.5 font-display text-lg font-black text-ink">{users.length}</p>
          </div>
        </div>
        <div className={cn(
          "card flex items-center gap-3 rounded-2xl border p-4 shadow-sm",
          telecallerSeats && telecallerSeats.used >= telecallerSeats.limit
            ? "border-red-100 bg-red-50/50" : "border-emerald-100 bg-emerald-50/50",
        )}>
          <div className={cn(
            "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border-subtle bg-white",
            telecallerSeats && telecallerSeats.used >= telecallerSeats.limit ? "text-red-600" : "text-emerald-600",
          )}>
            <Phone size={18} />
          </div>
          <div className="min-w-0">
            <p className="font-body text-xs font-bold uppercase tracking-wider text-ink-muted">Telecaller Seats</p>
            <p className="mt-0.5 font-display text-lg font-black text-ink">
              {telecallerSeats ? `${telecallerSeats.used}/${telecallerSeats.limit}` : "—"}
            </p>
          </div>
        </div>
      </div>

      {tab === "roles" ? (
        <div className="grid gap-5 xl:h-[calc(100vh-9rem)] xl:grid-cols-[380px_minmax(0,1fr)]">
          <aside className="card rounded-3xl p-4">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" size={16} />
              <input
                className="input"
                style={{ paddingLeft: "2.5rem" }}
                placeholder="Search roles..."
                value={roleSearch}
                onChange={(e) => setRoleSearch(e.target.value)}
              />
            </div>
            <div className="mt-4 space-y-2">
              {filteredRoles.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
                  <Inbox size={28} className="text-ink-muted/40" />
                  <p className="font-body text-xs text-ink-muted">No roles match &quot;{roleSearch}&quot;.</p>
                </div>
              ) : (
                filteredRoles.map((item) => {
                  const active = editingRoleId === item.id;
                  const activeModules = moduleActiveCount(item.permissions);
                  const RoleIcon = item.is_telecaller ? Phone : ShieldCheck;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => startRole(item)}
                      className={cn(
                        "w-full rounded-2xl border p-4 text-left transition-all",
                        active ? "border-primary/30 bg-primary-light shadow-sm" : "border-border-subtle bg-white hover:border-primary/20 hover:bg-surface-subtle hover:shadow-sm",
                      )}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-3">
                          <span className={cn(
                            "grid h-10 w-10 shrink-0 place-items-center rounded-2xl",
                            active ? "bg-white text-primary shadow-sm" : avatarColor(item.id),
                          )}>
                            <RoleIcon size={16} />
                          </span>
                          <div className="min-w-0">
                            <p className="truncate font-body text-sm font-bold text-ink">{item.name}</p>
                            <p className="font-body text-xs text-ink-muted">{activeModules} modules active</p>
                          </div>
                        </div>
                        <span className="shrink-0 rounded-full bg-white px-2 py-1 font-label text-[10px] font-bold text-ink-muted">
                          {item.is_system_template ? "System" : "Custom"}
                        </span>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </aside>

          <form onSubmit={saveRole} className="card flex min-h-0 flex-col overflow-hidden rounded-3xl p-0 xl:h-full">
            <div className="shrink-0 border-b border-border-subtle bg-gradient-to-br from-surface-subtle via-white to-primary-light/20 px-5 py-3 sm:px-6">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <h2 className="font-display text-base font-black text-ink">
                    Role Details: {roleDraft.name || editingRole?.name || "New Role"}
                  </h2>
                  <p className="mt-1 font-body text-xs text-ink-muted">Configure module-level read and write access. Delete access is intentionally omitted.</p>
                </div>
                {canWrite && (
                  <button type="button" onClick={resetRole} className="btn-primary inline-flex h-8 w-fit items-center justify-center gap-1.5 px-2.5 text-xs">
                    <Plus size={12} /> Add New Role
                  </button>
                )}
              </div>
              <div className="mt-3">
                <label className="mb-1.5 block font-label text-[9px] font-black uppercase tracking-wider text-ink-muted">Role title</label>
                <input
                  className="input h-9 bg-white text-sm"
                  placeholder="Example: Telecaller"
                  value={roleDraft.name}
                  onChange={(e) => setRoleDraft((d) => ({ ...d, name: e.target.value }))}
                  disabled={!canWrite}
                  required
                />
              </div>
            </div>

            <div className="min-h-0 flex-1 overscroll-contain overflow-y-auto overflow-x-auto p-3 sm:p-4">
              <table className="w-full min-w-[760px] border-separate border-spacing-0 overflow-hidden rounded-2xl border border-border-subtle bg-white">
                <thead className="sticky top-0 z-10">
                  <tr className="bg-surface-subtle shadow-[0_1px_0_0_var(--color-border-subtle)]">
                    <th className="w-[48%] px-4 py-3 text-left font-label text-[10px] font-black uppercase tracking-wider text-ink-muted">Module / Resource</th>
                    <th className="px-4 py-3 text-center font-label text-[10px] font-black uppercase tracking-wider text-ink-muted">Read</th>
                    <th className="px-4 py-3 text-center font-label text-[10px] font-black uppercase tracking-wider text-ink-muted">Write</th>
                    <th className="px-4 py-3 text-right font-label text-[10px] font-black uppercase tracking-wider text-ink-muted">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {moduleGroups.map((group) => (
                    <Fragment key={group.name}>
                      <tr>
                        <td colSpan={4} className="border-t border-border-subtle bg-surface-subtle/70 px-4 py-2">
                          <div className="flex items-center gap-1.5 font-label text-[10px] font-black uppercase tracking-widest text-primary/80">
                            <Folder size={11} /> {group.name}
                          </div>
                        </td>
                      </tr>
                      {group.modules.map((module) => {
                        const effectiveReadKeys = module.readKeys.filter((key) => catalogKeys.size === 0 || catalogKeys.has(key));
                        const effectiveWriteKeys = module.writeKeys.filter((key) => catalogKeys.size === 0 || catalogKeys.has(key));
                        const readChecked = hasAnyPermission(roleDraft.permissions, [...effectiveReadKeys, ...effectiveWriteKeys]);
                        const writeChecked = hasAnyPermission(roleDraft.permissions, effectiveWriteKeys);
                        const writeAvailable = effectiveWriteKeys.length > 0;
                        return (
                          <tr key={module.id} className="border-t border-border-subtle hover:bg-surface-subtle/40">
                            <td className="border-t border-border-subtle px-4 py-3">
                              <p className="font-body text-sm font-bold text-ink">{module.title}</p>
                              <p className="mt-1 font-body text-xs text-ink-muted">{module.description}</p>
                            </td>
                            <td className="border-t border-border-subtle px-4 py-3 text-center">
                              <CheckTick
                                checked={readChecked}
                                disabled={!canWrite}
                                onChange={(v) => setModuleAccess(module, "read", v)}
                                size="sm"
                                aria-label={`${module.title} read access`}
                              />
                            </td>
                            <td className="border-t border-border-subtle px-4 py-3 text-center">
                              <CheckTick
                                checked={writeChecked}
                                disabled={!canWrite || !writeAvailable}
                                onChange={(v) => setModuleAccess(module, "write", v)}
                                size="sm"
                                aria-label={`${module.title} write access`}
                              />
                            </td>
                            <td className="border-t border-border-subtle px-4 py-3 text-right">
                              <button
                                type="button"
                                onClick={() => clearModule(module)}
                                disabled={!canWrite}
                                className="inline-flex items-center gap-1 rounded-xl px-3 py-1.5 font-label text-xs font-bold text-ink-muted hover:bg-surface-subtle hover:text-ink"
                              >
                                <RotateCcw size={12} /> Clear
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex shrink-0 flex-col gap-3 border-t border-border-subtle px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="font-body text-xs text-ink-muted">{moduleActiveCount(roleDraft.permissions)} modules selected for this role.</p>
              {canWrite ? (
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                  {editingRole && !editingRole.is_system_template && (
                    <button
                      type="button"
                      disabled={deleting === `role:${editingRole.id}` || saving}
                      onClick={() => deleteRole(editingRole)}
                      className="inline-flex items-center justify-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-2 font-label text-sm font-bold text-red-700 transition-all hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {deleting === `role:${editingRole.id}` ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                      Delete Role
                    </button>
                  )}
                  <button type="submit" disabled={saving || deleting !== null} className="btn-primary justify-center">
                    {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                    {editingRoleId ? "Save Role" : "Create Role"}
                  </button>
                </div>
              ) : (
                <span className="rounded-full bg-surface-subtle px-3 py-2 font-label text-xs font-bold text-ink-muted">Read-only view</span>
              )}
            </div>
          </form>
        </div>
      ) : tab === "users" ? (
        <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
          {canWrite && (
          <form onSubmit={saveUser} className="card rounded-3xl space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="font-display text-base font-bold text-ink">
                  {editingOwner ? "Admin Calling Setup" : editingUserId ? "Edit User" : "Create User"}
                </h2>
                <p className="mt-1 font-body text-xs text-ink-muted">
                  {editingOwner
                    ? `${providerLabel(callingProvider)} details for ${editingOwner.name}. Uses no telecaller seat.`
                    : `Assign one role. Telecaller fields adapt to ${providerLabel(callingProvider)}.`}
                </p>
              </div>
              {(editingUserId || editingOwner) && <button type="button" onClick={resetUser} className="btn-secondary text-xs">New</button>}
            </div>
            <div className="grid gap-3">
              {!editingOwner && (
              <>
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" size={15} />
                <input className="input" style={{ paddingLeft: "2.25rem" }} placeholder="Full name" value={userDraft.full_name} onChange={(e) => setUserDraft((d) => ({ ...d, full_name: e.target.value }))} required />
              </div>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" size={15} />
                <input className="input" style={{ paddingLeft: "2.25rem" }} placeholder="Email" type="email" value={userDraft.email} onChange={(e) => setUserDraft((d) => ({ ...d, email: e.target.value }))} disabled={!!editingUserId} required />
              </div>
              <div className="relative">
                <ShieldCheck className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" size={15} />
                <select className="input" style={{ paddingLeft: "2.25rem" }} value={userDraft.role_id} onChange={(e) => setUserDraft((d) => ({ ...d, role_id: e.target.value }))} required>
                  {roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
                </select>
              </div>
              </>
              )}
              {!editingUserId && !editingOwner && (
                <div className="flex gap-2">
                  <input className="input flex-1 font-mono" placeholder="Temporary password" type={showDraftPassword ? "text" : "password"} value={userDraft.temporary_password} onChange={(e) => setUserDraft((d) => ({ ...d, temporary_password: e.target.value }))} required />
                  <button type="button" className="btn-secondary px-3" onClick={() => setShowDraftPassword((value) => !value)} title={showDraftPassword ? "Hide password" : "Show password"}>
                    {showDraftPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => setUserDraft((d) => ({ ...d, temporary_password: makePassword() }))}>
                    <KeyRound size={14} />
                  </button>
                </div>
              )}
              {(selectedRoleIsTelecaller || editingOwner) && (
                <div className="grid gap-3 rounded-2xl border border-primary/15 bg-primary-light/50 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 font-label text-[10px] font-black uppercase tracking-wider text-primary">
                      {editingOwner ? <Crown size={13} /> : <Users size={13} />}
                      <span>{editingOwner ? "Admin" : "Telecaller"} setup - {providerLabel(callingProvider)}</span>
                    </div>
                    {!editingOwner && telecallerSeats && (
                      <span className={cn(
                        "rounded-full px-2 py-0.5 font-label text-[10px] font-bold",
                        atSeatLimit ? "bg-red-100 text-red-700" : "bg-white text-ink-muted",
                      )}>
                        {telecallerSeats.used}/{telecallerSeats.limit} seats
                      </span>
                    )}
                  </div>
                  <input className="input bg-white" placeholder="Phone number" value={userDraft.phone} onChange={(e) => setUserDraft((d) => ({ ...d, phone: e.target.value }))} />
                  {callingProvider === "telecmi" && (
                    <input className="input bg-white" placeholder="Cloud Telephony User ID" value={userDraft.telecmi_agent_id} onChange={(e) => setUserDraft((d) => ({ ...d, telecmi_agent_id: e.target.value }))} />
                  )}
                  {editingOwner && (
                    <p className="font-body text-xs text-ink-muted">
                      This is the number and User ID used when you call as <span className="font-bold">Admin (me)</span> from the dialer. The User ID must match the one shown in your {providerLabel(callingProvider)} console.
                    </p>
                  )}
                  {atSeatLimit && (
                    <p className="font-body text-xs text-red-700">
                      Telecaller seat limit reached ({telecallerSeats!.used}/{telecallerSeats!.limit}). Delete a telecaller or request more seats from Subscriptions to add another.
                    </p>
                  )}
                </div>
              )}
            </div>
            <button
              type="submit"
              disabled={saving || atSeatLimit}
              title={atSeatLimit ? `Telecaller seat limit reached (${telecallerSeats!.used}/${telecallerSeats!.limit})` : undefined}
              className="btn-primary w-full justify-center"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : (editingUserId || editingOwner) ? <CheckCircle2 size={14} /> : <UserPlus size={14} />}
              {editingOwner ? "Save Calling Setup" : editingUserId ? "Save User" : "Create User"}
            </button>
          </form>
          )}

          <div className="card rounded-3xl overflow-hidden">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-display text-base font-bold text-ink">Users</h2>
              <span className="rounded-full bg-surface-subtle px-2.5 py-1 font-label text-[10px] font-bold text-ink-muted">{users.length} total</span>
            </div>
            {users.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
                <Inbox size={32} className="text-ink-muted/40" />
                <p className="font-body text-sm text-ink-muted">No users yet.</p>
              </div>
            ) : (
              <div className="divide-y divide-border-subtle">
                {users.map((user) => (
                  <div key={user.user_id} className="flex flex-col gap-3 py-3.5 transition-colors hover:bg-surface-subtle/40 sm:flex-row sm:items-center sm:justify-between sm:rounded-xl sm:px-2">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className={cn(
                        "grid h-10 w-10 shrink-0 place-items-center rounded-full font-label text-xs font-black",
                        user.role === "owner" ? "bg-primary-light text-primary" : avatarColor(user.user_id),
                      )}>
                        {user.role === "owner" ? <Crown size={16} /> : initials(user.full_name || user.email)}
                      </span>
                      <div className="min-w-0">
                        <p className="truncate font-body text-sm font-bold text-ink">{user.full_name || user.email}</p>
                        <p className="truncate font-body text-xs text-ink-muted">{user.email}</p>
                        <div className="mt-1 flex flex-wrap gap-2">
                          <span className="rounded-full bg-primary-light px-2 py-0.5 font-label text-[10px] font-bold text-primary">{user.role === "owner" ? "Master" : user.role_name}</span>
                          {user.force_password_reset && <span className="rounded-full bg-amber-100 px-2 py-0.5 font-label text-[10px] font-bold text-amber-700">Reset required</span>}
                          {user.role === "owner" && <span className="rounded-full bg-surface-subtle px-2 py-0.5 font-label text-[10px] font-bold text-ink-muted">Admin</span>}
                          {user.role === "owner" && user.caller_profile && !ownerCallingReady(user, callingProvider) && (
                            <span className="rounded-full bg-amber-100 px-2 py-0.5 font-label text-[10px] font-bold text-amber-700">Calling setup incomplete</span>
                          )}
                          {user.role !== "owner" && user.caller_profile && <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-label text-[10px] font-bold text-emerald-700">Team visible</span>}
                        </div>
                        {(user.caller_profile?.phone || (callingProvider === "telecmi" && user.caller_profile?.telecmi_agent_id)) && (
                          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-body text-xs text-ink-muted">
                            {user.caller_profile?.phone && (
                              <span className="inline-flex items-center gap-1">
                                <Phone size={11} className="shrink-0" />
                                {user.caller_profile.phone}
                              </span>
                            )}
                            {callingProvider === "telecmi" && user.caller_profile?.telecmi_agent_id && (
                              <span
                                className="inline-flex items-center gap-1"
                                title={`${providerLabel(callingProvider)} User ID`}
                              >
                                <span className="font-label text-[10px] font-bold uppercase tracking-wider">ID</span>
                                <span className="font-mono">{maskAgentId(user.caller_profile.telecmi_agent_id)}</span>
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                    {role === "owner" && user.role === "owner" && user.caller_profile && (
                      <div className="flex shrink-0 gap-2">
                        <button
                          type="button"
                          className="btn-secondary px-3"
                          onClick={() => startOwnerCalling(user)}
                          title={`Edit ${providerLabel(callingProvider)} setup`}
                        >
                          <Pencil size={14} />
                        </button>
                      </div>
                    )}
                    {canWrite && user.role !== "owner" && (
                      <div className="flex shrink-0 gap-2">
                        <button type="button" className="btn-secondary px-3" onClick={() => startUser(user)}><Pencil size={14} /></button>
                        <button type="button" className="btn-secondary px-3" onClick={() => resetPassword(user)}><KeyRound size={14} /></button>
                        {role === "owner" && callingProvider === "sim_basic" && user.caller_profile && (
                          <button
                            type="button"
                            className="btn-secondary px-3"
                            onClick={() => setSyncTokenDialogUser(user)}
                            title="Anril Sync token"
                          >
                            <Smartphone size={14} />
                          </button>
                        )}
                        <button
                          type="button"
                          className="inline-flex h-10 items-center justify-center rounded-xl border border-red-200 bg-red-50 px-3 text-red-700 transition-all hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                          onClick={() => deleteUser(user)}
                          disabled={deleting === `user:${user.user_id}` || saving}
                          title="Delete user"
                        >
                          {deleting === `user:${user.user_id}` ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="card rounded-3xl overflow-hidden">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-base font-bold text-ink">Audit Log</h2>
            <span className="rounded-full bg-surface-subtle px-2.5 py-1 font-label text-[10px] font-bold text-ink-muted">{auditLoading ? "—" : auditTotal} total</span>
          </div>
          {auditLoading ? (
            <div className="flex justify-center py-16"><Loader2 size={24} className="animate-spin text-primary" /></div>
          ) : auditEntries.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
              <Inbox size={32} className="text-ink-muted/40" />
              <p className="font-body text-sm text-ink-muted">No audit events yet.</p>
            </div>
          ) : (
            <div className="divide-y divide-border-subtle">
              {auditEntries.map((entry) => {
                const user = users.find((u) => u.user_id === entry.actor_user_id);
                const metaText = entry.metadata && Object.keys(entry.metadata).length > 0
                  ? Object.entries(entry.metadata)
                      .filter(([, v]) => v !== null && v !== undefined && v !== "********")
                      .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
                      .join(" · ")
                  : "";
                return (
                  <div key={entry.id} className="flex flex-col gap-1 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-2">
                    <div className="min-w-0">
                      <p className="font-body text-sm font-bold text-ink">
                        {entry.action} <span className="font-body text-xs font-normal text-ink-muted">by {user?.full_name || user?.email || entry.actor_role || "system"}</span>
                      </p>
                      {metaText && <p className="mt-0.5 truncate font-body text-xs text-ink-muted">{metaText}</p>}
                    </div>
                    <p className="shrink-0 font-label text-[10px] font-bold text-ink-muted">{new Date(entry.created_at).toLocaleString()}</p>
                  </div>
                );
              })}
            </div>
          )}
          {auditTotal > 50 && (
            <div className="mt-4 flex items-center justify-end gap-2">
              <button type="button" className="btn-secondary px-3" disabled={auditPage <= 1} onClick={() => setAuditPage((p) => p - 1)}>Prev</button>
              <span className="font-body text-xs text-ink-muted">Page {auditPage}</span>
              <button type="button" className="btn-secondary px-3" disabled={auditPage * 50 >= auditTotal} onClick={() => setAuditPage((p) => p + 1)}>Next</button>
            </div>
          )}
        </div>
      )}

      <ConfirmModal
        open={confirmState !== null}
        onClose={() => setConfirmState(null)}
        onConfirm={() => confirmState?.onConfirm()}
        title={confirmState?.title ?? ""}
        description={confirmState?.description ?? ""}
        tone={confirmState?.tone ?? "primary"}
        confirmLabel={confirmState?.confirmLabel}
        loading={saving || deleting !== null || mintingSyncToken !== null}
      />

      {syncTokenDialogUser && (
        <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-card bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-muted text-primary">
                  <Smartphone size={18} />
                </div>
                <h3 className="text-lg font-bold text-ink">
                  Anril Sync — {syncTokenDialogUser.full_name || syncTokenDialogUser.email}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setSyncTokenDialogUser(null)}
                className="text-ink-muted hover:text-ink"
                aria-label="Close"
              >
                <X size={18} />
              </button>
            </div>
            <p className="mb-4 text-sm text-ink-secondary">
              View this caller&apos;s current token, or regenerate it if it was lost — regenerating invalidates the current one immediately.
            </p>
            <div className="flex flex-col gap-2">
              <button
                type="button"
                className="btn-secondary w-full justify-center"
                onClick={() => viewSyncToken(syncTokenDialogUser)}
                disabled={viewingSyncToken === syncTokenDialogUser.caller_profile?.id}
              >
                {viewingSyncToken === syncTokenDialogUser.caller_profile?.id ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Eye size={14} />
                )}
                View current token
              </button>
              <button
                type="button"
                className="w-full justify-center rounded-xl border border-danger/30 bg-danger/5 px-4 py-2.5 text-sm font-bold text-danger transition-colors hover:bg-danger/10"
                onClick={() => regenerateSyncToken(syncTokenDialogUser)}
              >
                Regenerate token
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
