"use client";
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { API_URL } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";

interface RoleCtx {
  role: "owner" | "caller" | null;
  roleId: string | null;
  roleName: string | null;
  roleSlug: string | null;
  permissions: string[];
  callerId: string | null;
  enabledFeatures: string[];
  tenantName: string | null;
  isSystemAdmin: boolean;
  forcePasswordReset: boolean;
  bootstrapError: string | null;
  loading: boolean;
}

const AuthRoleContext = createContext<RoleCtx>({
  role: null,
  roleId: null,
  roleName: null,
  roleSlug: null,
  permissions: [],
  callerId: null,
  enabledFeatures: ["whatsapp", "telecalling"],
  tenantName: null,
  isSystemAdmin: false,
  forcePasswordReset: false,
  bootstrapError: null,
  loading: true,
});

const CACHE_KEY = "aira_role_cache";

interface CacheEntry {
  userId: string;
  role: "owner" | "caller";
  roleId: string | null;
  roleName: string | null;
  roleSlug: string | null;
  permissions: string[];
  callerId: string | null;
  enabledFeatures: string[];
  tenantName: string | null;
  isSystemAdmin: boolean;
  forcePasswordReset: boolean;
}

function readCache(): CacheEntry | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function writeCache(data: CacheEntry) {
  try { localStorage.setItem(CACHE_KEY, JSON.stringify(data)); } catch {}
}

export function clearRoleCache() {
  try { localStorage.removeItem(CACHE_KEY); } catch {}
}

export function AuthRoleProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<"owner" | "caller" | null>(null);
  const [roleId, setRoleId] = useState<string | null>(null);
  const [roleName, setRoleName] = useState<string | null>(null);
  const [roleSlug, setRoleSlug] = useState<string | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [callerId, setCallerId] = useState<string | null>(null);
  const [enabledFeatures, setEnabledFeatures] = useState<string[]>(["whatsapp", "telecalling"]);
  const [tenantName, setTenantName] = useState<string | null>(null);
  const [isSystemAdmin, setIsSystemAdmin] = useState(false);
  const [forcePasswordReset, setForcePasswordReset] = useState(false);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Render free-tier sleeps after 15min idle and takes 30-60s to wake.
    // 12 retries × 5s = 60s window, generous enough to survive cold-start.
    async function fetchMe(retries = 12, delayMs = 5000): Promise<void> {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      const currentUserId = session?.user?.id;

      // Apply cache only if it belongs to the current user — prevents stale owner
      // role from bleeding into a caller session when the same browser is reused.
      let appliedCachedRole: "owner" | "caller" | null = null;
      if (currentUserId) {
        const cached = readCache();
        if (cached && cached.userId === currentUserId) {
          appliedCachedRole = cached.role;
          setRole(cached.role);
          setRoleId(cached.roleId ?? null);
          setRoleName(cached.roleName ?? null);
          setRoleSlug(cached.roleSlug ?? null);
          setPermissions(cached.permissions ?? []);
          setCallerId(cached.callerId);
          setEnabledFeatures(cached.enabledFeatures);
          setTenantName(cached.tenantName ?? null);
          setIsSystemAdmin(cached.isSystemAdmin);
          setForcePasswordReset(cached.forcePasswordReset ?? false);
          setLoading(false);
        }
      }

      const auth: Record<string, string> = session ? { Authorization: `Bearer ${session.access_token}` } : {};
      let lastError = "Could not load your workspace access.";
      for (let attempt = 1; attempt <= retries; attempt++) {
        try {
          const res = await fetch(`${API_URL}/api/v1/team/me`, { headers: auth });
          if (!res.ok) {
            const body = await res.json().catch(() => null);
            const detail = typeof body?.detail === "string" ? body.detail : `team/me ${res.status}`;
            lastError = detail;
            // This account's tenant membership was removed (e.g. an admin deleted
            // this telecaller) while the browser session was still open. There is
            // nothing to retry -- surfacing a dead-end "Retry" loop just confuses
            // the user, so sign them out and send them back to login instead.
            if (res.status === 403 && detail.startsWith("No tenant associated")) {
              clearRoleCache();
              await supabase.auth.signOut({ scope: "local" });
              window.location.href = "/login?reason=removed";
              return;
            }
            if (![502, 503, 504].includes(res.status)) {
              setBootstrapError(detail);
              return;
            }
            throw new Error(detail);
          }
          const d = await res.json();
          const newRole = d.role as "owner" | "caller";
          const newRoleId = d.role_id ?? null;
          const newRoleName = d.role_name ?? null;
          const newRoleSlug = d.role_slug ?? null;
          const newPermissions = d.permissions ?? [];
          const newFeatures = d.enabled_features ?? ["whatsapp", "telecalling"];
          const newTenantName = d.tenant_name ?? null;
          const newIsAdmin = d.is_system_admin ?? false;
          const newCallerId = d.caller_id ?? null;
          const newForcePasswordReset = d.force_password_reset ?? false;
          if (currentUserId) {
            writeCache({
              userId: currentUserId,
              role: newRole,
              roleId: newRoleId,
              roleName: newRoleName,
              roleSlug: newRoleSlug,
              permissions: newPermissions,
              callerId: newCallerId,
              enabledFeatures: newFeatures,
              tenantName: newTenantName,
              isSystemAdmin: newIsAdmin,
              forcePasswordReset: newForcePasswordReset,
            });
          }
          // The cached role we already committed to was wrong (role changed
          // server-side since the cache was written). Reload so the page mounts
          // fresh with the corrected role instead of unmounting the owner-only
          // tree mid-render with requests still in flight.
          if (appliedCachedRole && appliedCachedRole !== newRole) {
            window.location.reload();
            return;
          }
          setRole(newRole);
          setRoleId(newRoleId);
          setRoleName(newRoleName);
          setRoleSlug(newRoleSlug);
          setPermissions(newPermissions);
          setCallerId(newCallerId);
          setEnabledFeatures(newFeatures);
          setTenantName(newTenantName);
          setIsSystemAdmin(newIsAdmin);
          setForcePasswordReset(newForcePasswordReset);
          setBootstrapError(null);
          return;
        } catch (err) {
          lastError = err instanceof Error ? err.message : lastError;
          if (attempt < retries) {
            await new Promise((r) => setTimeout(r, delayMs));
          }
        }
      }
      setBootstrapError(lastError);
    }

    fetchMe().finally(() => setLoading(false));
  }, []);

  return (
    <AuthRoleContext.Provider value={{ role, roleId, roleName, roleSlug, permissions, callerId, enabledFeatures, tenantName, isSystemAdmin, forcePasswordReset, bootstrapError, loading }}>
      {children}
    </AuthRoleContext.Provider>
  );
}

export const useAuthRole = () => useContext(AuthRoleContext);
