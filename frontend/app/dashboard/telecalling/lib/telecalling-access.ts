/**
 * Who may open the Dialer and who may place calls from it.
 * Shared by the Dialer page (TelecallingView) and the "Dial a number" page so the two
 * can never drift apart. Pure on purpose: no hooks, easy to test.
 */
export type TelecallingRole = "owner" | "caller" | null;

export function resolveTelecallingAccess(role: TelecallingRole, permissions: string[]) {
  const canDial = role === "owner" || permissions.includes("telecalling.dialer");
  const canViewTelecalling =
    role === "owner" ||
    permissions.includes("telecalling.dialer.view") ||
    permissions.includes("telecalling.dialer") ||
    permissions.includes("leads.view") ||
    permissions.includes("team.view");
  return { canDial, canViewTelecalling };
}
