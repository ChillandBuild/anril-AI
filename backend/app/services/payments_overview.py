"""My business > Payments & advance: the read-only side of the page.

The advance rule itself is read and saved through the existing Orders API (/orders/advance-rule);
this module only explains what already happens around it: who may refund, when balance reminders
go out, what the customer is told after a refund, and which ways of paying are ready.
Every piece fails on its own: a piece that can't be read is left plain, never a 500.
"""
import logging

from app.services.orders import REMINDER_DAYS, REMINDER_HOURS_IST

logger = logging.getLogger(__name__)

# Copy of what the customer gets today. The source of truth is services/orders.compose,
# kind == "refund" (orders.py ~720); keep these two in step.
REFUND_MESSAGE = {
    "razorpay": "Vanakkam [name], the refund of [amount] for order [order number] from [your shop] has started. "
                "It reaches your account in 5-7 working days.",
    "other": "Vanakkam [name], [your shop] has given back [amount] for order [order number] by [cash, UPI or bank].",
}


def _hour_text(hour: int) -> str:
    suffix = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12} {suffix}"


def _day_list(days: tuple[int, ...]) -> str:
    words = [str(d) for d in days]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def reminders_text() -> str:
    """"With the Ready message, then on days 1, 3 and 7, between 10 AM and 7 PM"."""
    return (
        f"With the Ready message, then on days {_day_list(REMINDER_DAYS)}, "
        f"between {_hour_text(REMINDER_HOURS_IST[0])} and {_hour_text(REMINDER_HOURS_IST[1])}"
    )


def mask_gstin(gstin: str) -> str:
    """33ABCDE1234F1Z5 -> 33AB••••••••1Z5 (first 4 and last 3 shown)."""
    g = (gstin or "").strip().upper()
    if len(g) < 8:
        return "•" * len(g)
    return g[:4] + "•" * (len(g) - 7) + g[-3:]


def refund_who(db, tenant_id: str) -> list[str]:
    """The owner, then every role that has "Refund orders" (deals.refund)."""
    names = ["Owner"]
    try:
        rows = db.table("tenant_roles").select("name, permissions").eq("tenant_id", tenant_id).execute().data or []
        names += sorted({r["name"] for r in rows if r.get("name") and "deals.refund" in (r.get("permissions") or [])},
                        key=str.lower)
    except Exception as e:
        logger.warning("payments overview: roles for tenant %s failed: %s", tenant_id, e)
    return names


def _setting_is_set(db, tenant_id: str, key: str) -> bool:
    rows = db.table("app_settings").select("value").eq("tenant_id", tenant_id).eq("key", key).limit(1).execute().data or []
    return bool(rows and str(rows[0].get("value") or "").strip())


def razorpay_way(db, tenant_id: str) -> dict:
    """Ready when Connect with Razorpay was done, or both pasted keys are saved."""
    try:
        ok = _setting_is_set(db, tenant_id, "razorpay_oauth_account_id") or (
            _setting_is_set(db, tenant_id, "razorpay_key_id") and _setting_is_set(db, tenant_id, "razorpay_key_secret")
        )
    except Exception as e:
        logger.warning("payments overview: razorpay check for tenant %s failed: %s", tenant_id, e)
        return {"key": "razorpay", "ok": None, "detail": "Could not check Razorpay right now"}
    return {"key": "razorpay", "ok": ok,
            "detail": "Razorpay is connected. Customers can pay from a link" if ok
            else "Razorpay is not connected. Connect it to send pay links"}


def gst_way(db, tenant_id: str) -> dict:
    try:
        from app.services.business_details import get_business_details
        gstin = (get_business_details(tenant_id, db).get("gstin") or "").strip()
    except Exception as e:
        logger.warning("payments overview: gstin for tenant %s failed: %s", tenant_id, e)
        return {"key": "gst", "ok": None, "detail": "Could not check your GSTIN right now"}
    if gstin:
        return {"key": "gst", "ok": True, "detail": f"GSTIN {mask_gstin(gstin)}"}
    return {"key": "gst", "ok": False, "detail": "No GSTIN — bills are simple bills"}


def overview(db, tenant_id: str) -> dict:
    return {
        "refund_who": refund_who(db, tenant_id),
        "balance_reminders": reminders_text(),
        "refund_message": dict(REFUND_MESSAGE),
        "ways_to_pay": [
            razorpay_way(db, tenant_id),
            {"key": "in_shop", "ok": True, "detail": "Cash, UPI and card are recorded in New bill"},
            gst_way(db, tenant_id),
        ],
    }
