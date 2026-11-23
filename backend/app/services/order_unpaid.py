"""New bill hint: the picked customer already owes on an order ("1 unpaid order · Open it").

Unpaid = the same rule as "Still to collect" on Orders: not paid in full or cancelled, an advance
taken or a pay link sent (payment_state waiting/advance), with a balance left. Only a hint: nothing
here merges or changes an order."""
from app.services.deals import balance_paise
from app.services.orders import payment_state
from app.services.reports_common import paged


def unpaid_for_lead(db, tenant_id: str, lead_id: str) -> dict:
    """{"unpaid_orders": n, "unpaid_order_id": the newest one, or None}. This tenant's orders only."""
    rows = paged(lambda: db.table("deals").select("id,stage,total_paise,paid_paise,created_at")
                 .eq("tenant_id", tenant_id).eq("lead_id", lead_id).not_.in_("stage", ["won", "lost"]))
    unpaid = [d for d in rows if payment_state(d) in ("waiting", "advance") and balance_paise(d) > 0]
    unpaid.sort(key=lambda d: str(d.get("created_at") or ""), reverse=True)
    return {"unpaid_orders": len(unpaid), "unpaid_order_id": unpaid[0]["id"] if unpaid else None}
