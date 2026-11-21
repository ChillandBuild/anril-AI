"""Executors for the AI-native deal engine's tools (see services/deal_engine.py).

The model ASKS; this module DECIDES. Every executor validates against the tenant's own
configuration and the session row, and returns a refusal message (which the caller feeds
back to the model) instead of doing anything unsafe:

  - prices and amounts come from config / the session snapshot, never from tool arguments
  - a payment link is refused until every required detail is saved or skipped
  - a paid session can never be re-selected or get a second link
  - at most one menu per turn

Session reads and writes go through intake's own helpers (looked up as module attributes at
call time), so the Deals-board sync, the staleness sweep, the Razorpay webhook and the Astro
bridge keep working on the same intake_sessions rows.
"""
import json
import logging
import re
import uuid
from dataclasses import dataclass, field

from app.services import astro_bridge, deal_engine
from app.services import intake
from app.services.astro_normalize import (
    format_time_12h,
    is_unknown_time,
    normalize_date,
    normalize_gender,
    normalize_place,
    normalize_time,
    time_needs_meridiem,
)

logger = logging.getLogger(__name__)

MENU_BUTTON_TEXT = "Options"  # English default; deal_turn._label_list swaps in the customer's language


@dataclass(frozen=True)
class DealContext:
    config: dict
    db: object
    lead_id: str
    tenant_id: str
    phone: str
    catalog: dict = field(default_factory=dict)  # catalog item id -> row, this turn's candidates
    max_images: int = 0
    offerings_enabled: bool = True  # package tools + DEAL STATE (WhatsApp tenants with packages)
    known_prices: frozenset = frozenset()  # rupee figures from the catalog and orders, for the price guard
    payment_concern: bool = False  # they say they paid / want a refund: no new link or quote this turn
    buttons_enabled: bool = False  # the channel can show tappable options (WhatsApp)
    business_details: dict = field(default_factory=dict)  # Business Details page values Anril may share when asked
    rejected_detail_tap: bool = False


@dataclass(frozen=True)
class Outcome:
    menu: dict | None = None
    payment_link: str | None = None
    refusals: tuple[str, ...] = ()
    handover: bool = False
    quote_text: str | None = None  # product quote summary + its payment link, rendered by code
    image_item_ids: tuple[str, ...] = ()
    file_ids: tuple[str, ...] = ()  # shop files (catalog_files) sent after the reply


class _Turn:
    """Mutable accumulator for one turn's tool calls (an implementation detail)."""

    def __init__(self, last_assistant_text: str = "", customer_message: str = ""):
        self.last_assistant_text = last_assistant_text
        self.customer_message = customer_message
        self.menu: dict | None = None
        self.payment_link: str | None = None
        self.refusals: list[str] = []
        self.handover = False
        self.quote_text: str | None = None
        self.image_item_ids: list[str] = []
        self.file_ids: list[str] = []
        self.link_failed = False

    def outcome(self) -> Outcome:
        return Outcome(
            self.menu, self.payment_link, tuple(self.refusals), self.handover,
            self.quote_text, tuple(self.image_item_ids), tuple(self.file_ids),
        )


def _fields(ctx: DealContext) -> list[dict]:
    return ctx.config.get("fields") or []


def _session(ctx: DealContext) -> dict | None:
    return intake._get_active_session(ctx.lead_id, ctx.tenant_id, ctx.db)


def _ready_status(ctx: DealContext, collected: dict, skipped) -> str:
    missing = deal_engine.missing_details(_fields(ctx), collected, skipped)
    return deal_engine.COLLECTING_STATUS if missing else deal_engine.CONFIRM_STATUS


def _find_node(nodes: list[dict], key: str) -> dict | None:
    for node in nodes:
        if node.get("key") == key:
            return node
        found = _find_node(node.get("options") or [], key)
        if found:
            return found
    return None


def _labels(ctx: DealContext, keys: list[str]) -> str:
    by_key = {f["key"]: f["label"] for f in _fields(ctx)}
    return ", ".join(f"{k} ({by_key.get(k, k)})" for k in keys)


def _offering_changed(session: dict, leaf: dict, addons: list[dict], total: int) -> bool:
    """False when select_offering re-picks what the session already has: its link stays valid
    and must not be cancelled or cleared."""
    if not session.get("package_key"):
        return False
    have_addons = sorted(a.get("key") for a in session.get("selected_addons") or [])
    return (
        session.get("package_key") != leaf["key"]
        or session.get("total_amount_paise") != total
        or have_addons != sorted(a["key"] for a in addons)
    )


async def _close_open_session(ctx: DealContext, session: dict, reason: str) -> bool:
    """Cancel one open booking of THIS tenant (and its live payment link, best effort). False
    when it was no longer open in the state we saw, e.g. a payment landed a moment ago: that
    write wins and nothing is closed."""
    return await intake.cancel_open_session(ctx.db, {**session, "tenant_id": ctx.tenant_id}, reason=reason)


async def _select_offering(ctx: DealContext, args: dict, turn: _Turn) -> str | None:
    packages = intake.normalize_packages(ctx.config)
    key = args.get("key")
    found = intake._find_leaf(packages, key) if key else None
    if not found:
        node = _find_node(packages, key) if key else None
        if node and node.get("options"):
            children = ", ".join(c["key"] for c in deal_engine._active(node["options"]))
            return f"select_offering refused: '{key}' is a category, not something to buy. Choose one of: {children}."
        return f"select_offering refused: '{key}' is not one of the offerings."
    leaf, path = found
    if not leaf.get("active", True):
        return f"select_offering refused: '{key}' is not available any more."

    addons = deal_engine._active(leaf.get("addons") or [])
    addon_keys = args.get("addon_keys")
    if addons and addon_keys is None:
        names = ", ".join(a["key"] for a in addons)
        return (
            f"select_offering refused: '{key}' has add-ons ({names}). Ask the customer about them, "
            "then call again with addon_keys (an empty list if they want none)."
        )
    wanted = list(addon_keys or [])
    unknown = [k for k in wanted if k not in {a["key"] for a in addons}]
    if unknown:
        return f"select_offering refused: unknown add-on {', '.join(unknown)}."
    chosen = [dict(a) for a in addons if a["key"] in wanted]
    total = deal_engine.offering_total(leaf, chosen)

    session = _session(ctx)
    if session and session["status"] == deal_engine.PAID_STATUS:
        # A paid booking is finished and stays exactly as it is. A repeat customer starts a new
        # one next to it at once, instead of waiting for the 48h paid -> resolved auto-resolve.
        if args.get("new_booking") is not True:
            return (
                "select_offering refused: that booking is already paid and cannot change. If the "
                "customer wants another, separate booking, call select_offering with new_booking true."
            )
        session = None
    if session and args.get("new_booking") is True and session.get("package_key"):
        # D6: a second, separate booking. The old one (and its link) is closed BEFORE the new
        # session is opened, so there is never more than one open deal for this lead.
        if not await _close_open_session(ctx, session, "Replaced by a new booking"):
            return (
                "select_offering refused: the earlier booking changed while you were replying. "
                "Read DEAL STATE again before continuing."
            )
        session = None
    if session is None:
        session = intake._create_session(ctx.lead_id, ctx.tenant_id, ctx.db)
    before = dict(session)
    repointed = _offering_changed(before, leaf, chosen, total)
    patch = intake._package_patch(leaf, path, total_amount_paise=total) | {
        "selected_addons": chosen,
        "field_schema": _fields(ctx),
        "status": _ready_status(ctx, session.get("collected_data") or {}, session.get("skipped_fields") or []),
    }
    if repointed:
        # The stored Razorpay id stays as the "last link" (it feeds the next link's idempotency
        # key); only a NEW link replaces it.
        patch |= {"payment_link": None, "amount_paise": None, "gst_percent": None, "gst_amount_paise": None}
    intake._update_session(session["id"], patch, ctx.db)
    if repointed:
        # After the session stopped pointing at the old link: a failed cancel can't strand the lead.
        await intake.cancel_session_link(ctx.db, before)
    return None


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b")
_NAMED_DATE_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?,?\s+(\d{2,4})\b", re.IGNORECASE)


def _impossible_date(text: str) -> bool:
    """True only for a date that cannot exist (31-02-1995, 30 February). Anything the code
    cannot read ('around 1995') is left to the model and the customer."""
    import calendar
    match = _NUMERIC_DATE_RE.search(text)
    if match:
        day, month, year = (int(g) for g in match.groups())
    else:
        match = _NAMED_DATE_RE.search(text)
        if not match or match.group(2)[:3].lower() not in _MONTHS:
            return False
        day, month, year = int(match.group(1)), _MONTHS[match.group(2)[:3].lower()], int(match.group(3))
    if year < 100:
        year += 1900 if year > 30 else 2000
    if not 1 <= month <= 12:
        return True
    return not 1 <= day <= calendar.monthrange(year, month)[1]


def _astro_connected(ctx: DealContext) -> bool:
    """AstroTamil clients get stricter detail checks. A settings read must never break a turn."""
    try:
        return astro_bridge.is_connected(ctx.tenant_id)
    except Exception as e:
        logger.warning(f"AstroTamil connection check failed for tenant {ctx.tenant_id}: {e}")
        return False


# A detail AstroTamil cannot answer without. Only birth time may be skipped (it is then sent as
# 12:00 with a note), and the name, which falls back to the lead's.
_UNSKIPPABLE_ROLES = {
    "birth_date": "date of birth", "gender": "gender", "question": "question", "birth_place": "place of birth",
}


def _astro_value(role: str, key: str, text: str) -> tuple[str | None, str | None]:
    """(value to store, problem). Only for AstroTamil clients: the date, time and gender must be
    ones AstroTamil can use, and are stored in one fixed form so what is saved is what is sent."""
    if role == "birth_date":
        if _impossible_date(text):
            return None, f"{key} '{text}' is not a real date; ask them to check it"
        date = normalize_date(text)
        if date:
            return date, None
        return None, (
            f"{key} '{text}' is not a date that can be used. Ask for the day, month and a 4-digit "
            "year, e.g. 19-11-2003"
        )
    if role == "birth_time":
        if is_unknown_time(text) and not normalize_time(text):
            return None, (
                f"{key} '{text}' means they do not know their birth time. Ask ONCE for an approximate time "
                "(a rough hour with AM or PM, like 6 am). If they still cannot say, call skip_detail for "
                f"{key}: it is then sent with a 12:00 placeholder and a note for the astrologer."
            )
        time = normalize_time(text)
        if not time:
            return None, f"{key} '{text}' is not a time that can be used. Ask for it like 10:30 am"
        if time_needs_meridiem(text):
            return None, f"{key} '{text}' could be AM or PM. Ask: is that AM (morning) or PM (evening)?"
        return format_time_12h(time), None
    if role == "birth_place" and not normalize_place(text):
        return None, f"{key} '{text}' is not a place. Ask for the town or city they were born in"
    if role == "gender" and not normalize_gender(text):
        return None, f"{key} '{text}' is not clear. Ask: Male or Female?"
    return text, None


def _canonical_option(field: dict, value: str) -> str | None:
    for option in field.get("options") or []:
        if option.strip().lower() == value.strip().lower():
            return option
    return None


def _clean_details(ctx: DealContext, raw: dict) -> tuple[dict, list[str]]:
    """(accepted values, problems). Unknown keys and blanks are dropped silently."""
    by_key = {f["key"]: f for f in _fields(ctx)}
    accepted: dict[str, str] = {}
    problems: list[str] = []
    astro = _astro_connected(ctx)
    for key, value in raw.items():
        field = by_key.get(key)
        text = str(value or "").strip()
        if not field or not text:
            continue
        if field.get("options"):
            canonical = _canonical_option(field, text)
            if canonical is None:
                problems.append(f"{key} must be one of: {', '.join(field['options'])}")
                continue
            text = canonical
        role = astro_bridge.field_role(key) if astro else None
        if role:
            text, problem = _astro_value(role, key, text)
            if problem:
                problems.append(problem)
                continue
        elif field.get("type") == "date" and _impossible_date(text):
            problems.append(f"{key} '{text}' is not a real date; ask them to check it")
            continue
        accepted[key] = text
    return accepted, problems


def _open_session_for_details(ctx: DealContext, tool: str) -> tuple[dict | None, str | None]:
    session = _session(ctx)
    if not session or not session.get("package_key"):
        return None, f"{tool} refused: no offering is selected yet. Call select_offering first."
    if session["status"] == deal_engine.PAID_STATUS:
        return None, f"{tool} refused: the customer has already paid."
    return session, None


def _status_after_change(ctx: DealContext, session: dict, collected: dict, skipped: list) -> str:
    if session["status"] == deal_engine.AWAITING_PAYMENT_STATUS:
        return session["status"]
    return _ready_status(ctx, collected, skipped)


async def _save_details(ctx: DealContext, args: dict, turn: _Turn) -> str | None:
    if ctx.rejected_detail_tap:
        return "save_details refused: this message tapped an old or invalid detail button. Ask the customer again."
    session, refusal = _open_session_for_details(ctx, "save_details")
    if refusal:
        return refusal
    if args.get("session_id") and session["id"] != args["session_id"]:
        return "save_details refused: the booking changed after that detail button was shown. Ask for the current details again."
    raw = args.get("fields")
    if not isinstance(raw, dict):
        return "save_details refused: pass fields as an object of detail key to value."
    accepted, problems = _clean_details(ctx, raw)
    if not accepted:
        return "save_details refused: " + ("; ".join(problems) or "none of those are details this business collects.")
    collected = {**(session.get("collected_data") or {}), **accepted}
    skipped = [k for k in (session.get("skipped_fields") or []) if k not in accepted]
    intake._update_session(session["id"], {
        "collected_data": collected,
        "skipped_fields": skipped,
        "status": _status_after_change(ctx, session, collected, skipped),
    }, ctx.db)
    intake.adopt_lead_name(
        ctx.db, ctx.lead_id, ctx.tenant_id, intake.resolve_customer_name(collected, _fields(ctx)),
    )
    if problems:
        return "save_details saved the rest, but: " + "; ".join(problems) + ". Ask again for those."
    return None


async def _skip_detail(ctx: DealContext, args: dict, turn: _Turn) -> str | None:
    session, refusal = _open_session_for_details(ctx, "skip_detail")
    if refusal:
        return refusal
    key = args.get("key")
    if key not in {f["key"] for f in _fields(ctx)}:
        return f"skip_detail refused: '{key}' is not a detail this business collects."
    needed = _UNSKIPPABLE_ROLES.get(astro_bridge.field_role(key)) if _astro_connected(ctx) else None
    if needed:
        return f"skip_detail refused: the astrologer cannot answer without their {needed}. Ask for it; do not skip it."
    collected = session.get("collected_data") or {}
    skipped = list(dict.fromkeys([*(session.get("skipped_fields") or []), key]))
    intake._update_session(session["id"], {
        "skipped_fields": skipped,
        "status": _status_after_change(ctx, session, collected, skipped),
    }, ctx.db)
    return None


_PAYMENT_CONCERN_REFUSAL = (
    "refused: the customer says they already paid or wants a refund, and a person is checking. "
    "Do not send a link or a quote this turn."
)


async def _create_payment_link(ctx: DealContext, args: dict, turn: _Turn) -> str | None:
    if ctx.payment_concern:
        return "create_payment_link " + _PAYMENT_CONCERN_REFUSAL
    session = _session(ctx)
    if not session or not session.get("package_key"):
        return "create_payment_link refused: no offering is selected yet."
    if session["status"] == deal_engine.PAID_STATUS:
        return "create_payment_link refused: the customer has already paid. Do not send another link."
    collected = session.get("collected_data") or {}
    missing = deal_engine.missing_details(_fields(ctx), collected, session.get("skipped_fields") or [])
    if missing:
        return f"create_payment_link refused: still needed from the customer: {_labels(ctx, missing)}."
    if _astro_connected(ctx):
        # The same check the push to AstroTamil makes after payment: a customer who has paid for
        # a question AstroTamil then refuses is the failure this prevents.
        unusable = astro_bridge.unusable_for_push(
            collected, session.get("skipped_fields"), ctx.phone, session.get("trigger_reason"),
        )
        if unusable:
            return (
                f"create_payment_link refused: the astrologer cannot use their {', '.join(unusable)} yet. "
                "Ask the customer for it again, then try again."
            )
    prices = deal_engine.current_prices(ctx.config, session)
    if not prices:
        return "create_payment_link refused: the chosen offering is not available any more or has no price."
    package_amount, subtotal = prices
    moved = deal_engine.price_moved(ctx.config, session)
    if moved and moved[1] > moved[0] and args.get("customer_agreed_new_price") is not True:
        # The business raised the price after the customer agreed: never surprise them with it.
        return (
            f"create_payment_link refused: the price went up from {deal_engine._rupees(moved[0])} to "
            f"{deal_engine._rupees(moved[1])} since they agreed. Tell them the new price and ask if they "
            "want to continue; call again with customer_agreed_new_price true only after they say yes."
        )
    gst_fields = intake.gst_session_fields(subtotal, deal_engine.gst_percent(ctx.config))
    amount = gst_fields["amount_paise"]  # what the link charges: subtotal + GST

    if turn.link_failed:
        return "create_payment_link refused: it already failed this turn and a team member was asked to help."
    existing = session.get("payment_link")
    if deal_engine.link_is_live(session, amount):
        turn.payment_link = existing
        return None

    name = intake.resolve_customer_name(collected, _fields(ctx)) or ctx.phone
    noun = (ctx.config.get("service_noun") or "consultation").capitalize()
    ref = f"IN-{uuid.uuid4().hex[:8].upper()}"
    # Razorpay hands back the SAME link for a repeated key, so a regeneration must change it:
    # the old link's expiry is unique per link made (0 when there was none).
    # The last Razorpay link's id is unique per link made, so a re-link after a cancel (which may
    # leave the expiry unchanged) still gets a fresh key instead of the cancelled link back.
    previous = deal_engine.parse_time(session.get("payment_link_expires_at"))
    previous_epoch = int(previous.timestamp()) if previous else 0
    previous_plink = session.get("razorpay_payment_link_id") or ""
    before = dict(session)
    try:
        link = await intake.create_payment_link(
            idempotency_key=f"booking:{session['id']}:{session['package_key']}:{amount}:{previous_epoch}:{previous_plink}:payment_link",
            notes={"booking_id": session["id"], "booking_ref": ref},
            amount_paise=amount,
            customer_name=name,
            customer_phone=ctx.phone,
            description=intake.gst_link_description(
                f"{noun} — {name} ({ref})", subtotal, deal_engine.gst_percent(ctx.config),
            ),
            tenant_id=ctx.tenant_id,
        )
    except Exception:
        logger.exception("Payment link creation failed for session %s", session["id"])
        _handover_for_failed_link(ctx, turn, "Payment link could not be created for a package")
        return (
            "create_payment_link failed: a team member has been asked to send the payment link. Tell "
            "the customer that, in your own words, without promising a time."
        )
    stored = intake._update_session(session["id"], {
        "status": deal_engine.AWAITING_PAYMENT_STATUS, **gst_fields, **intake.link_store_patch(link),
        "package_amount_paise": package_amount, "total_amount_paise": subtotal,
    }, ctx.db, unless_status=deal_engine.PAID_STATUS)
    if stored is False:  # explicit False: _update_session skipped the write (doubles may return None)
        # The customer paid while the link was being made: the write was skipped, so this new
        # link is stored nowhere. Kill it (best effort) and never send it -- a second payment
        # on it would be a double charge.
        await intake.cancel_payment_link(link.get("razorpay_payment_link_id"), ctx.tenant_id)
        return "create_payment_link refused: the customer has already paid. Do not send another link."
    turn.payment_link = link["payment_link_url"]
    # Cancel the replaced link only now that the new one is stored (best effort).
    await intake.cancel_session_link(ctx.db, before, keep_plink_id=link.get("razorpay_payment_link_id"))
    return None


def build_level_menu(level: list[dict]) -> dict | None:
    """Buttons or a list for one level of offerings; None when WhatsApp can't show them."""
    mode = intake._tap_mode(level)
    if mode == "text":
        return None
    if mode == "buttons":
        buttons = intake._build_buttons(level)
        return {"kind": "buttons", "options": [b["title"] for b in buttons], "buttons": buttons,
                "offering_keys": [n["key"] for n in level]}
    sections = intake._build_list_sections(level)
    titles = [row["title"] for s in sections for row in s["rows"]]
    return {"kind": "list", "options": titles, "sections": sections, "button_text": MENU_BUTTON_TEXT,
            "offering_keys": [n["key"] for n in level]}


def top_level_menu(ctx: DealContext) -> tuple[list[dict], dict | None]:
    """The active top-level offerings and their menu."""
    level = deal_engine._active(intake.normalize_packages(ctx.config))
    return level, build_level_menu(level)


def _menu_for(kind_level: list[dict], ctx: DealContext, turn: _Turn, *, addons: bool) -> str | None:
    level = kind_level + [intake._NO_ADDONS_OPTION] if addons else kind_level
    menu = build_level_menu(level)
    if menu is None:
        return "show_options refused: there are too few or too many choices for buttons. Describe them in words."
    previous = turn.last_assistant_text
    from app.services.choices import is_vague
    if previous and all(f"[{title}]" in previous for title in menu["options"]) and is_vague(turn.customer_message):
        return (
            "show_options refused: those exact options were just shown in your previous message. "
            "Answer in words instead, or ask which one they prefer."
        )
    turn.menu = menu
    return None


async def _show_options(ctx: DealContext, args: dict, turn: _Turn) -> str | None:
    if turn.menu:
        return "show_options refused: options were already shown this turn."
    packages = intake.normalize_packages(ctx.config)
    under = args.get("under")
    if args.get("of") == "addons":
        session = _session(ctx)
        key = under or (session or {}).get("package_key")
        found = intake._find_leaf(packages, key) if key else None
        addons = deal_engine._active(found[0].get("addons") or []) if found else []
        if not addons:
            return "show_options refused: that offering has no add-ons."
        return _menu_for(addons, ctx, turn, addons=True)
    if not under:
        named = _named_category(packages, turn.customer_message)
        under = named["key"] if named else None  # "long term course details" -> that category's options
    if under:
        node = _find_node(packages, under)
        if not node or not node.get("options"):
            return f"show_options refused: '{under}' is not a category."
        return _menu_for(deal_engine._active(node["options"]), ctx, turn, addons=False)
    return _menu_for(deal_engine._active(packages), ctx, turn, addons=False)


def _named_category(packages: list[dict], message: str) -> dict | None:
    """The one top-level category the customer named, if exactly one."""
    text = re.sub(r"[-_]", " ", (message or "").lower())
    found = [
        n for n in deal_engine._active(packages)
        if n.get("options") and re.sub(r"[-_]", " ", n["name"].lower()) in text
    ]
    return found[0] if len(found) == 1 else None


def _assigned_to(ctx: DealContext) -> str | None:
    try:
        row = ctx.db.table("leads").select("assigned_to").eq("id", ctx.lead_id).maybe_single().execute()
        return (row.data or {}).get("assigned_to") if row else None
    except Exception:
        return None


def _handover_for_failed_link(ctx: DealContext, turn: "_Turn", reason: str) -> None:
    """A customer ready to pay must never be left waiting on a link nobody will send."""
    open_handover(ctx, reason)
    turn.handover = True
    turn.link_failed = True


def open_handover(ctx: DealContext, reason: str) -> None:
    """One pending handover per lead (the helper de-duplicates). Never raises."""
    try:
        from app.services import ai_reply
        ai_reply._trigger_chat_escalation(
            lead_id=ctx.lead_id, reason=reason, tenant_id=ctx.tenant_id,
            assigned_to=_assigned_to(ctx), db=ctx.db,
        )
    except Exception:
        logger.exception("Handover failed for lead %s", ctx.lead_id)


async def _close_deal(ctx: DealContext, args: dict, turn: _Turn) -> str | None:
    """The customer explicitly declined the open booking. The model decides that (in any
    language); this only closes what is really open, never a paid booking."""
    session = _session(ctx)
    if session is None:
        return "close_deal refused: there is no open booking to close."
    if session["status"] == deal_engine.PAID_STATUS:
        return "close_deal refused: the customer has already paid. Do not close a paid booking."
    if not await _close_open_session(ctx, session, "Customer declined"):
        return "close_deal: the booking changed at the same moment and was left as it is. Do not say it was closed."
    return None


async def _hand_to_human(ctx: DealContext, args: dict, turn: _Turn) -> str | None:
    reason = str(args.get("reason") or "").strip() or "The AI asked for a person to take over"
    open_handover(ctx, reason[:200])
    turn.handover = True
    return None


# ---------------------------------------------------------------- products (catalog)

ORDER_LOOKBACK_LIMIT = 5


def lead_orders(db, tenant_id: str, lead_id: str) -> list[dict]:
    """The lead's most recent product orders (not consultation bookings) with their lines,
    for the ORDERS prompt block. Never raises."""
    try:
        deals = (
            db.table("deals")
            .select("id,deal_number,stage,total_paise")
            .eq("tenant_id", tenant_id)
            .eq("lead_id", lead_id)
            .is_("intake_session_id", "null")
            .order("created_at", desc=True)
            .limit(ORDER_LOOKBACK_LIMIT)
            .execute()
        ).data or []
        for deal in deals:
            deal["items"] = (
                db.table("deal_items").select("name,qty").eq("deal_id", deal["id"]).eq("tenant_id", tenant_id).execute()
            ).data or []
        return deals
    except Exception:
        logger.exception("Order lookup failed for lead %s", lead_id)
        return []


def _open_awaiting_deals(ctx: DealContext) -> list[dict]:
    """This lead's unpaid product quotes (link sent, or its link expired: the deal stays open
    and is re-linked), newest first, each with its lines. Never raises."""
    try:
        deals = (
            ctx.db.table("deals")
            .select("id,stage,payment_link,total_paise,link_expires_at,razorpay_payment_link_id")
            .eq("tenant_id", ctx.tenant_id)
            .eq("lead_id", ctx.lead_id)
            .eq("stage", "awaiting_payment")
            .is_("intake_session_id", "null")
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        ).data or []
        for deal in deals:
            deal["items"] = (
                ctx.db.table("deal_items").select("catalog_item_id,qty,name,line_total_paise")
                .eq("deal_id", deal["id"]).eq("tenant_id", ctx.tenant_id).execute()
            ).data or []
        return deals
    except Exception:
        logger.exception("Open deal lookup failed for lead %s", ctx.lead_id)
        return []


def _same_lines(deal: dict, lines: list[dict]) -> bool:
    have = sorted((i.get("catalog_item_id"), i.get("qty")) for i in deal.get("items") or [])
    want = sorted((line["catalog_item_id"], line["qty"]) for line in lines)
    return have == want


async def _recommend_item(ctx: DealContext, args: dict, turn: _Turn) -> str | None:
    item_id = args.get("item_id")
    item = ctx.catalog.get(item_id)
    if not item:
        return f"recommend_catalog_item refused: '{item_id}' is not in the catalog shown to you."
    if item.get("stock_quantity") == 0:
        return f"recommend_catalog_item refused: {item['name']} is out of stock. Say so honestly and offer an alternative."
    if item_id in turn.image_item_ids:
        return None
    if ctx.max_images and len(turn.image_item_ids) >= ctx.max_images:
        return f"recommend_catalog_item: only {ctx.max_images} item photo(s) per reply; describe the rest in words."
    turn.image_item_ids.append(item_id)
    if item.get("price_paise") is not None:
        from app.services import deals
        deals.upsert_quoted_deal(
            ctx.tenant_id, ctx.lead_id, {"catalog_item_id": item_id, "name": item["name"], "qty": 1}, db=ctx.db,
        )
    return None


def _quote_lines(ctx: DealContext, args: dict) -> tuple[list[dict], str | None]:
    item_ids = args.get("item_ids") or []
    quantities = args.get("quantities") or []
    if not isinstance(item_ids, list) or not item_ids:
        return [], "send_quote refused: pass the item_ids the customer wants."
    lines: list[dict] = []
    for idx, item_id in enumerate(item_ids):
        item = ctx.catalog.get(item_id)
        if not item or item.get("price_paise") is None:
            return [], f"send_quote refused: '{item_id}' has no price in the catalog. Ask the team or offer another item."
        qty = quantities[idx] if idx < len(quantities) else 1
        if not isinstance(qty, int) or qty < 1:
            return [], "send_quote refused: each quantity must be a whole number of at least 1. Ask how many they want."
        lines.append({"catalog_item_id": item_id, "name": item["name"], "qty": qty})
    return lines, None


def _stock_problem(ctx: DealContext, lines: list[dict]) -> str | None:
    from app.services import deals
    tracked = [line["catalog_item_id"] for line in lines if ctx.catalog[line["catalog_item_id"]].get("stock_quantity") is not None]
    try:
        held = deals.held_quantities(ctx.tenant_id, tracked, ctx.db) if tracked else {}
    except Exception:
        logger.warning("held_quantities failed for lead %s", ctx.lead_id)
        held = {}
    for line in lines:
        stock = ctx.catalog[line["catalog_item_id"]].get("stock_quantity")
        if stock is None:
            continue
        available = stock - held.get(line["catalog_item_id"], 0)
        if available < line["qty"]:
            return f"send_quote refused: only {max(available, 0)} of {line['name']} available right now."
    return None


def _quote_text(items: list[dict], total_paise: int, link: str) -> str:
    from app.services import deals
    return deals.quote_summary_block(items, total_paise) + f"\n\nPay here: {link}"


def _quote_failed(ctx: DealContext, turn: _Turn) -> str:
    _handover_for_failed_link(ctx, turn, "Payment link could not be created for a product order")
    return (
        "send_quote failed: a team member has been asked to send the quote and payment link. "
        "Tell the customer that, in your own words, without promising a time."
    )


async def _send_quote(ctx: DealContext, args: dict, turn: _Turn) -> str | None:
    if ctx.payment_concern:
        return "send_quote " + _PAYMENT_CONCERN_REFUSAL
    if turn.quote_text:
        return "send_quote refused: a quote was already sent this turn."
    lines, problem = _quote_lines(ctx, args)
    if problem:
        return problem
    problem = _stock_problem(ctx, lines)
    if problem:
        return problem
    from app.services import deals
    for deal in _open_awaiting_deals(ctx):
        if not _same_lines(deal, lines):
            continue
        link = deal["payment_link"]
        if not deals._link_is_live(deal):
            # Never hand the customer a dead link: make a new one (the old one is cancelled).
            try:
                link = (await deals.send_payment_link(ctx.tenant_id, deal["id"], send_whatsapp_message=False, db=ctx.db))["payment_link"]
            except Exception:
                logger.exception("Relinking deal %s failed for lead %s", deal["id"], ctx.lead_id)
                return _quote_failed(ctx, turn)
        turn.quote_text = _quote_text(deal["items"], deal["total_paise"], link)
        return None
    try:
        created = await deals.create_deal(
            ctx.tenant_id, ctx.lead_id, lines, "whatsapp", "awaiting_payment", send_link=False, db=ctx.db,
        )
    except Exception:
        logger.exception("create_deal (send_quote) failed for lead %s", ctx.lead_id)
        created = {}
    if not created.get("payment_link"):
        return _quote_failed(ctx, turn)
    turn.quote_text = _quote_text(created["items"], created["deal"]["total_paise"], created["payment_link"])
    return None


async def _send_form(ctx: DealContext, args: dict, turn: _Turn) -> str | None:
    """WhatsApp Forms the client lets the AI send (whatsapp_form_reach). Code checks the form is
    one of those, published with its latest changes; the form goes out under the reply."""
    from app.services import whatsapp_form_reach as reach
    from app.services import whatsapp_forms as wf

    if not ctx.buttons_enabled:
        return "send_form refused: forms only open on WhatsApp."
    if turn.menu:
        return "send_form refused: something to tap is already attached to this reply."
    form_id = str(args.get("form_id") or "")
    allowed = {f["id"] for f in reach.ai_forms(ctx.db, ctx.tenant_id)}
    if form_id not in allowed:
        return "send_form refused: that is not one of the forms you may send."
    design = wf.get_design(ctx.db, ctx.tenant_id, form_id)
    form = wf.live_custom_form(ctx.db, ctx.tenant_id, design) if design else None
    if not form:
        return "send_form refused: that form isn't available right now. Carry on in the chat."
    turn.menu = {"kind": "form", "design_id": form_id, "cta": form["cta"], "options": []}
    return None


async def _send_file(ctx: DealContext, args: dict, turn: _Turn) -> str | None:
    """A shop file (price list, size chart...) goes out after the reply (services/catalog_files.py)."""
    from app.services import catalog_files

    file_id = str(args.get("file_id") or "")
    if file_id in turn.file_ids:
        return None
    if len(turn.file_ids) >= catalog_files.MAX_PER_REPLY:
        return f"send_file: at most {catalog_files.MAX_PER_REPLY} files per reply."
    turn.file_ids.append(file_id)
    return None


async def _note_stock_request(ctx: DealContext, args: dict, turn: _Turn) -> str | None:
    """The customer asked for something out of stock: they go on "Asked but out of stock"
    (services/stock_asks.py), and on the back-in-stock list once wants_message is true."""
    from app.services import stock_asks
    from app.services.deals import variant_label

    item = ctx.catalog.get(args.get("item_id"))
    if not item:
        return f"note_out_of_stock_request refused: '{args.get('item_id')}' is not in the catalog shown to you."
    wanted = " ".join(str(args.get("variant") or "").split()).lower()
    variant = None
    if wanted:
        variant = next((v for v in item.get("variants") or [] if variant_label(v).lower() == wanted
                        or wanted in {(v.get("size") or "").lower(), (v.get("colour") or "").lower()}), None)
        if not variant:
            return f"note_out_of_stock_request refused: {item['name']} has no size/colour '{args.get('variant')}'."
        if (variant.get("stock_quantity") or 0) > 0:
            return f"note_out_of_stock_request refused: {item['name']} {variant_label(variant)} IS in stock; offer it."
    elif item.get("stock_quantity") != 0:
        return f"note_out_of_stock_request refused: {item['name']} is in stock; offer it (or name the size/colour that is out)."
    try:
        stock_asks.record_ask(ctx.db, ctx.tenant_id, lead_id=ctx.lead_id, item_id=item["id"],
                              variant_id=variant["id"] if variant else None,
                              wants_message=bool(args.get("wants_message")), source="ai")
    except Exception:
        logger.warning("Couldn't save an out-of-stock request for lead %s", ctx.lead_id, exc_info=True)
    return None


_EXECUTORS = {
    deal_engine.TOOL_SHOW_OPTIONS: _show_options,
    deal_engine.TOOL_SELECT_OFFERING: _select_offering,
    deal_engine.TOOL_SAVE_DETAILS: _save_details,
    deal_engine.TOOL_SKIP_DETAIL: _skip_detail,
    deal_engine.TOOL_CREATE_PAYMENT_LINK: _create_payment_link,
    deal_engine.TOOL_HAND_TO_HUMAN: _hand_to_human,
    deal_engine.TOOL_CLOSE_DEAL: _close_deal,
    "recommend_catalog_item": _recommend_item,
    "send_quote": _send_quote,
    "send_form": _send_form,
    "note_out_of_stock_request": _note_stock_request,
    "send_file": _send_file,
}


def _parse_args(raw) -> dict | None:
    try:
        parsed = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


_STATE_TOOLS = frozenset({deal_engine.TOOL_SELECT_OFFERING, deal_engine.TOOL_SAVE_DETAILS, deal_engine.TOOL_SKIP_DETAIL})


async def _auto_link(ctx: DealContext, turn: _Turn) -> None:
    """A choice was made or the last detail arrived this turn and nothing is missing: the
    customer is ready to pay, so the link goes out now. Live evals found the model saying
    "here is your new link" after a package switch without ever asking for one."""
    if ctx.payment_concern or turn.payment_link or turn.link_failed:
        return
    session = _session(ctx)
    if not session or session.get("status") != deal_engine.CONFIRM_STATUS:
        return
    refusal = await _create_payment_link(ctx, {}, turn)
    if refusal:
        turn.refusals.append(refusal)


async def apply_tool_calls(
    tool_calls: list[dict], ctx: DealContext, *, last_assistant_text: str = "", auto_link: bool = False,
    customer_message: str = "",
) -> Outcome:
    """Run the deal tools in the order the model asked. Unknown tool names (catalog, quick
    replies) are left for the caller. Never raises: a failure becomes a refusal."""
    turn = _Turn(last_assistant_text, customer_message)
    changed_state = False
    for call in tool_calls or []:
        func = call.get("function") or {}
        name = func.get("name")
        executor = _EXECUTORS.get(name)
        if executor is None:
            continue
        args = _parse_args(func.get("arguments"))
        if args is None:
            turn.refusals.append(f"{name} refused: the arguments were not valid JSON.")
            continue
        try:
            refusal = await executor(ctx, args, turn)
        except Exception:
            logger.exception("Deal tool %s failed for lead %s", name, ctx.lead_id)
            refusal = f"{name} failed unexpectedly. Do not claim it happened."
        if refusal:
            turn.refusals.append(refusal)
        elif name in _STATE_TOOLS:
            changed_state = True
    if auto_link and changed_state:
        await _auto_link(ctx, turn)
    return turn.outcome()
