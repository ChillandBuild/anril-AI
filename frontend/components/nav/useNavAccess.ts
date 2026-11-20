import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { claudeSettingsOn } from "@/components/settingsNavigation";
import { useSubscription } from "@/app/dashboard/contexts/SubscriptionContext";
import { TC_FEATURE_MAP, TC_PERMISSION_MAP, TELECALLING_ITEMS, type NavAccess, type TelecallingPage } from "./navSections";

export interface NavAccessInput {
  role: "owner" | "caller" | null;
  permissions: string[];
  enabledFeatures: string[];
  subStatus: string;
}

export interface NavAccessState {
  access: NavAccess;
  /** The Telecalling pages this user can open (feature flags and permissions applied). */
  tcGroupItems: readonly TelecallingPage[];
  waEnabled: boolean;
  telecallingOn: boolean;
  canManageTeam: boolean;
}

/** Pure form of useNavAccess, so the rules can be tested without React. */
export function buildNavAccess({ role, permissions, enabledFeatures, subStatus }: NavAccessInput): NavAccessState {
  const waEnabled = enabledFeatures.includes("whatsapp");
  const outboundOn = enabledFeatures.includes("outbound_messaging");
  const inboundOn = enabledFeatures.includes("inbound_messaging");
  const messagingOn = outboundOn || inboundOn;
  // Telecalling is purchased as a SIM or Tele-CMI bundle (each pulls in its own
  // telecalling.* sub-features); there is no bare "telecalling" key anymore.
  const telecallingOn = enabledFeatures.some(
    (f) => f === "telecalling_sim" || f === "telecalling_telecmi" || f.startsWith("telecalling."),
  );
  const canManageTeam = role === "owner" || permissions.includes("team.manage");
  // Brain has its own Roles toggle (brain.view).
  const brainGate =
    subStatus === "active" &&
    messagingOn &&
    (role === "owner" || permissions.includes("brain.view"));

  const isSubscribed = subStatus === "active";
  const can = (permission: string) => role === "owner" || permissions.includes(permission);
  const canAny = (items: string[]) => role === "owner" || items.some((permission) => permissions.includes(permission));

  // Gate telecalling sub-items by sub-feature flags with backwards compatibility
  const hasTcSubFeatures = enabledFeatures.some((f) => f.startsWith("telecalling."));
  const visibleTcItems = hasTcSubFeatures
    ? TELECALLING_ITEMS.filter((item) => {
        const featureKey = TC_FEATURE_MAP[item.href];
        return !featureKey || enabledFeatures.includes(featureKey);
      })
    : TELECALLING_ITEMS;

  const tcGroupItems = visibleTcItems.filter((item) => {
    const permissionKeys = TC_PERMISSION_MAP[item.href];
    return !permissionKeys || canAny(permissionKeys);
  });

  const access: NavAccess = {
    isSubscribed,
    messagingOn,
    inboundOn,
    outboundOn,
    smsOn: enabledFeatures.includes("sms"),
    canServices: canAny(["services.view", "services.manage"]),
    canSettings: canAny(["settings.view", "settings.manage"]),
    brainGate,
    telecallingVisible: isSubscribed && telecallingOn && tcGroupItems.length > 0,
    can,
    canAny,
  };

  return { access, tcGroupItems, waEnabled, telecallingOn, canManageTeam };
}

/**
 * What this user may see in the menu. Shared by the sidebar and the page-header
 * chips so both follow the exact same rules. Call it before any early return.
 */
export function useNavAccess(): NavAccessState & { roleLoading: boolean; purchasedFeatures: string[]; claudeOn: boolean } {
  const { role, permissions, enabledFeatures, loading: roleLoading } = useAuthRole();
  const { status: subStatus, purchasedFeatures } = useSubscription();
  return {
    ...buildNavAccess({ role, permissions, enabledFeatures, subStatus }),
    roleLoading,
    purchasedFeatures,
    claudeOn: claudeSettingsOn(role, enabledFeatures),
  };
}
