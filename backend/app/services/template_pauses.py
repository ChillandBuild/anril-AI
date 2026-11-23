"""v9.2 #26 A WhatsApp template that is turned down or paused pauses everything that uses it.

on_template_status_change() is called when Meta reports a template status change:
  REJECTED / PAUSED / DISABLED -> every automation using the template is switched off (when it has a switch here)
                                  and recorded in automation_pauses with the reason; the owner gets a bell alert.
  APPROVED / REINSTATED        -> only what this log shows Anril paused is switched back on.
Any other status changes nothing. Returns how many automations were paused or resumed."""
import logging
from datetime import datetime, timezone

from app.services.automation_list import PAUSE_STATUSES, STATUS_WORDS, collect_automations, force_off, set_automation_on
from app.services.automation_store import owner_user_ids

logger = logging.getLogger(__name__)

BELL_TYPE = "template_paused"


def open_pauses(db, tenant_id: str) -> dict[str, dict]:
    """{automation_key: {reason, template_name, paused_at}} for what is paused right now. {} if the table is missing."""
    try:
        rows = (
            db.table("automation_pauses").select("automation_key, template_name, reason, paused_at, switched_off")
            .eq("tenant_id", tenant_id).is_("resumed_at", "null").limit(500).execute().data or []
        )
    except Exception as e:
        logger.warning(f"automations: pauses not read for {tenant_id}: {e}")
        return {}
    return {r["automation_key"]: r for r in rows}


def _bell_owners(db, tenant_id: str, template_name: str, status: str, names: list[str]) -> None:
    from app.services.notify import notify_user
    what = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
    message = f"{STATUS_WORDS[status]} ({template_name}). Paused: {what}. Fix the message, then turn them back on."
    for uid in owner_user_ids(db, tenant_id):
        notify_user(tenant_id, uid, BELL_TYPE, "Some automations are paused", message, db=db, push_url="/dashboard/automations")


def on_template_status_change(db, tenant_id: str, template_name: str, status: str) -> int:
    status = (status or "").upper()
    if not template_name or not tenant_id:
        return 0
    try:
        if status in PAUSE_STATUSES:
            return _pause(db, tenant_id, template_name, status)
        if status in ("APPROVED", "REINSTATED"):   # Meta's REINSTATED = approved again (templates.py maps it the same way)
            return _resume(db, tenant_id, template_name)
    except Exception as e:                        # a status update must never break the webhook that called us
        logger.error(f"automations: template {template_name} ({status}) not applied for {tenant_id}: {e}")
    return 0


def _pause(db, tenant_id: str, template_name: str, status: str) -> int:
    already = open_pauses(db, tenant_id)
    paused: list[dict] = []
    failed = 0
    for a in collect_automations(db, tenant_id):
        if a.get("template_name") != template_name:
            continue
        open_row = already.get(a["key"])
        if open_row and open_row.get("template_name") == template_name:
            continue                              # this template's pause is already logged (webhook retry)
        if a["switchable"] and not a["on"]:
            continue                              # the owner already has it off: nothing to pause
        try:                                      # one automation failing must not drop the others or their bell
            switched = False
            if a["switchable"]:
                force_off(db, tenant_id, a["key"])
                switched = True
            db.table("automation_pauses").insert({
                "tenant_id": tenant_id, "automation_key": a["key"], "automation_name": a["name"],
                "template_name": template_name, "reason": f"{STATUS_WORDS[status]} ({status.lower()})", "switched_off": switched,
            }).execute()
            paused.append(a)
        except Exception as e:
            failed += 1
            logger.error(f"automations: {a['key']} not paused for template {template_name} ({tenant_id}): {e}")
    if paused:
        try:
            _bell_owners(db, tenant_id, template_name, status, [a["name"] for a in paused])
        except Exception as e:
            logger.warning(f"automations: owner not told for {tenant_id}: {e}")
    return len(paused)


def _resume(db, tenant_id: str, template_name: str) -> int:
    rows = (
        db.table("automation_pauses").select("id, automation_key, switched_off")
        .eq("tenant_id", tenant_id).eq("template_name", template_name).is_("resumed_at", "null").execute().data or []
    )
    count = 0
    for r in rows:
        if r.get("switched_off"):
            try:
                set_automation_on(db, tenant_id, r["automation_key"], True)
            except (LookupError, ValueError) as e:
                logger.info(f"automations: {r['automation_key']} not switched back on: {e}")   # deleted since, or needs the owner
        db.table("automation_pauses").update({"resumed_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", r["id"]).execute()
        count += 1
    return count
