"""AI-native selling: the prompt blocks, tool schemas and guardrails that let the main
reply brain sell packages, collect a client's required details and send the payment link
itself, instead of a fixed step-by-step script (services/intake.route_intake).

Design: docs/plans/ai-native-conversation.md.

This module is the pure half: config in, text or schemas out. The executors that touch
the session store and Razorpay live in services/deal_actions.py; the model round-trip is
converse_once in the same file as the executors' caller. Money rules are enforced there,
never trusted to the model: prices come from config, the link comes from Razorpay, and a
link is refused until every required detail is saved or skipped.
"""
import re
from datetime import datetime, timedelta, timezone

PAID_STATUS = "paid"
AWAITING_PAYMENT_STATUS = "awaiting_payment"
COLLECTING_STATUS = "collecting"
CONFIRM_STATUS = "awaiting_confirmation"

# A stored link with less than this left is treated as dead: the customer needs time to
# open it and pay, and Razorpay's clock is not ours.
LINK_EXPIRY_MARGIN = timedelta(seconds=60)

TOOL_SHOW_OPTIONS = "show_options"
TOOL_SELECT_OFFERING = "select_offering"
TOOL_SAVE_DETAILS = "save_details"
TOOL_SKIP_DETAIL = "skip_detail"
TOOL_CREATE_PAYMENT_LINK = "create_payment_link"
TOOL_HAND_TO_HUMAN = "hand_to_human"
TOOL_CLOSE_DEAL = "close_deal"
DEAL_TOOL_NAMES = frozenset({
    TOOL_SHOW_OPTIONS, TOOL_SELECT_OFFERING, TOOL_SAVE_DETAILS,
    TOOL_SKIP_DETAIL, TOOL_CREATE_PAYMENT_LINK, TOOL_HAND_TO_HUMAN, TOOL_CLOSE_DEAL,
})

# A lead away at least this long from an open deal is asked "continue or something else?"
# unless their message already shows clear intent (blueprint D4).
RETURN_AFTER = timedelta(hours=24)
IST = timezone(timedelta(hours=5, minutes=30))

# "I paid", "pay pana", "status of my payment", "money deducted". Deliberately narrow:
# "how do I pay?" and "is it paid or free?" are ordinary buying talk, not a complaint.
_PAYMENT_COMPLAINT_RE = re.compile(
    r"\b(?:i|ive|i've|already|na)\s+(?:have\s+)?(?:\d+\s+)?paid\b"
    r"|\bpaid\s+the\s+money\b"
    r"|\bpay\s*pan(?:a|na|nen)\b"
    r"|\bpayment\s+(?:status|failed|not|done|problem|issue|pending|confirm)"
    r"|\bstatus\s+(?:of|for)\s+my\s+payment\b"
    r"|\bmoney\s+(?:deducted|debited|gone|cut)\b"
    # refunds and cancelling something paid for: a person decides these, never the AI
    r"|\brefund\w*"
    r"|\bmoney\s+back\b"
    r"|\breturn\s+(?:the\s+|my\s+)?(?:amount|money|payment)\b"
    r"|\bcancel\w*\s+(?:my\s+|the\s+)?(?:order|booking|payment|consultation|appointment|course)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"\w", re.UNICODE)


_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_AMOUNT_BEFORE_RE = re.compile(rf"(?:₹|\bRs\.?|\bINR)\s*({_NUMBER})", re.IGNORECASE)
_AMOUNT_AFTER_RE = re.compile(rf"({_NUMBER})\s*(?:Rs\b|rupees?\b|ரூபாய்)", re.IGNORECASE)
_NUMBER_RE = re.compile(_NUMBER)


def _intake():
    from app.services import intake
    return intake


def _active(nodes: list[dict]) -> list[dict]:
    return [n for n in nodes if n.get("active", True)]


def _leaves(nodes: list[dict]) -> list[dict]:
    found: list[dict] = []
    for node in _active(nodes):
        if node.get("options"):
            found.extend(_leaves(node["options"]))
        else:
            found.append(node)
    return found


def is_enabled(config: dict) -> bool:
    """The tenant's off switch plus at least one purchasable package."""
    if not config.get("enabled"):
        return False
    return bool(_leaves(_intake().normalize_packages(config)))


def _to_float(text: str) -> float:
    return float(text.replace(",", ""))


def _addon_sums(base: int, addons: list[dict]) -> set[int]:
    """The offering price alone and with every combination of its add-ons (paise)."""
    totals = {base}
    for addon in addons:
        totals |= {t + addon["amount_paise"] for t in totals}
    return totals


def gst_percent(config: dict) -> float:
    """The tenant's GST added on top of packages at payment (0 = off, or a business whose GST type adds none)."""
    return 0 if config.get("gst_blocked") else (config.get("gst_percent") or 0)


def allowed_prices(config: dict) -> set[float]:
    """Every rupee figure the business actually charges: each offering, alone or with any
    of its add-ons, and each of those totals with GST added when the tenant charges it."""
    allowed: set[float] = set()
    percent = gst_percent(config)
    for leaf in _leaves(_intake().normalize_packages(config)):
        totals = _addon_sums(leaf["amount_paise"], _active(leaf.get("addons") or []))
        allowed |= {t / 100 for t in totals}
        if percent:
            allowed |= {_intake().charge_paise(t, percent) / 100 for t in totals}
        allowed |= {a["amount_paise"] / 100 for a in _active(leaf.get("addons") or [])}
    return allowed


MAX_QUANTITY_MULTIPLE = 10


def price_multiples(prices_paise) -> set[float]:
    """Rupee figures for 1..10 units of each price: '2 pairs come to Rs 4,998' is a real price."""
    return {p * n / 100 for p in prices_paise if p for n in range(1, MAX_QUANTITY_MULTIPLE + 1)}


def unknown_prices(reply: str, config: dict, customer_message: str, extra_allowed=()) -> list[float]:
    """Rupee amounts in a draft reply that are neither a real price nor a number the
    customer just wrote. The model's knowledge base can hold an older price; code, not the
    model's good intentions, is what keeps it out of a message.

    Only active when the business has structured prices (packages, catalog or orders): a
    business that keeps all its prices in knowledge text has nothing to check against."""
    allowed = allowed_prices(config) | set(extra_allowed)
    if not allowed:
        return []
    found = {_to_float(a) for a in _AMOUNT_BEFORE_RE.findall(reply) + _AMOUNT_AFTER_RE.findall(reply)}
    said = {_to_float(n) for n in _NUMBER_RE.findall(customer_message or "")}
    return sorted(found - allowed - said)


BUSINESS_DETAIL_FIELDS = ("gstin", "email", "phone", "address")
_ASKS_FOR_DETAILS_RE = re.compile(
    r"\b(gst\w*|invoice|bill|receipt|tax|address|location|where|office|visit|email|e-?mail|mail|"
    r"phone|number|contact|call|company|registered|legal|enga|yenga)\b|முகவரி|எங்கே",
    re.IGNORECASE,
)


def business_detail_values(details: dict) -> dict[str, str]:
    """The identifying details a reply must not volunteer, by field."""
    details = details or {}
    return {k: str(details.get(k) or "").strip() for k in BUSINESS_DETAIL_FIELDS if str(details.get(k) or "").strip()}


def volunteered_details(reply: str, values: dict[str, str], customer_message: str) -> list[str]:
    """Business details in a reply the customer did not ask for (Business Details page is final;
    Anril shares a detail only when asked)."""
    if not values or _ASKS_FOR_DETAILS_RE.search(customer_message or ""):
        return []
    text = re.sub(r"\s+", "", (reply or "").lower())
    return [k for k, v in values.items() if len(v) >= 6 and re.sub(r"\s+", "", v.lower()) in text]


def business_facts_block(details: dict, *, gst_on_top: bool = False) -> str:
    """The business's own identity (Settings > Business details), so a lead asking for the
    GST number, the registered address or an invoice name gets the real answer, not a
    handover. Only filled fields are shown. gst_on_top: the Services page adds GST at
    payment, which overrides the Business Details include/exclude flag."""
    details = details or {}
    address = ", ".join(p for p in (details.get("address"), details.get("city")) if p)
    region = " ".join(p for p in (details.get("state"), details.get("pincode")) if p)
    address = ", ".join(p for p in (address, region) if p)
    facts = [
        ("Registered business name", details.get("legal_name")),
        ("Address", address),
        ("GSTIN", details.get("gstin")),
        ("Email", details.get("email")),
        ("Phone", details.get("phone")),
    ]
    lines = [f"- {label}: {value}" for label, value in facts if value]
    if not lines:
        return ""
    if gst_on_top:
        gst = "GST is added on top of the listed package prices at payment, so the payment total is higher than the listed price."
    elif details.get("prices_include_gst", True):
        gst = "Listed prices include GST."
    else:
        gst = "Listed prices exclude GST; a quote adds GST on top, so its total can be higher than the listed price."
    return (
        "\n\nBUSINESS DETAILS (official and final; they override anything your description or "
        "knowledge says about them):\n" + "\n".join(lines) + f"\n{gst}\n"
        "Share one of these only when the customer asks for it (an invoice, the GST number, the "
        "company name, the address, an email or a phone number), and then only that one. Never "
        "volunteer them."
    )


_ORDER_STAGE_TEXT = {
    "quoted": "price mentioned, no link yet",
    "awaiting_payment": "payment link sent, not paid yet",
    "won": "PAID",
    "lost": "cancelled",
}


def orders_block(deals: list[dict]) -> str:
    """The lead's recent product orders, so Anril knows what was quoted, sent and paid.
    Rendered by code; never includes a link the model could copy."""
    if not deals:
        return ""
    lines = []
    for deal in deals:
        items = ", ".join(f"{i['name']} × {i.get('qty', 1)}" for i in deal.get("items") or []) or "items"
        state = _ORDER_STAGE_TEXT.get(deal.get("stage"), deal.get("stage") or "")
        number = f"D-{int(deal.get('deal_number') or 0):04d}"  # same format as deals.format_deal_number
        lines.append(f"- {number}: {items} — {_rupees(deal.get('total_paise') or 0)} — {state}")
    return (
        "\n\nORDERS (this customer's recent product orders, from the system; trust these over the chat):\n"
        + "\n".join(lines)
        + "\nIf they ask about an order, answer from this. A PAID order is paid; never ask them to pay it "
        "again. If a link is sent but not paid and they want to pay, call send_quote again for the same "
        "items and quantities: the system resends the same link."
    )


def is_blank_message(message: str) -> bool:
    """Only emoji / punctuation ('?', '👍'): no words to answer, so continue the open booking."""
    return not _WORD_RE.search(message or "")


def is_payment_complaint(message: str) -> bool:
    return bool(_PAYMENT_COMPLAINT_RE.search(message or ""))


def missing_details(fields: list[dict], collected: dict, skipped) -> list[str]:
    """Keys of required details that are neither saved nor marked not-provided."""
    skipped_set = set(skipped or [])
    return [
        f["key"] for f in fields
        if not (collected or {}).get(f["key"]) and f["key"] not in skipped_set
    ]


def _rupees(amount_paise: int) -> str:
    return _intake()._rupees(amount_paise)


def _offering_lines(nodes: list[dict], indent: str = "") -> list[str]:
    lines: list[str] = []
    for node in _active(nodes):
        if node.get("options"):
            lines.append(f"{indent}- Category {node['name']} (key: {node['key']}) contains:")
            lines.extend(_offering_lines(node["options"], indent + "    "))
            continue
        line = f"{indent}- {node['name']} — {_rupees(node['amount_paise'])} (key: {node['key']}"
        if node.get("button_label"):
            line += f", button: {node['button_label']}"
        line += ")"
        if node.get("description"):
            line += f": {node['description']}"
        lines.append(line)
        for addon in _active(node.get("addons") or []):
            lines.append(
                f"{indent}    add-on {addon['name']} — +{_rupees(addon['amount_paise'])} (key: {addon['key']})"
            )
    return lines


def gst_note(config: dict) -> str:
    """One sentence for the prompt when GST is added at payment; empty when it is off."""
    percent = gst_percent(config)
    if not percent:
        return ""
    return (
        f"Listed package prices exclude {percent:g}% GST; GST is added at payment, so the payment "
        "total is higher than the listed price. Quote the listed price as the price; give the "
        "payment total (shown in DEAL STATE) only when they ask what they will pay."
    )


def offerings_block(config: dict) -> str:
    packages = _intake().normalize_packages(config)
    noun = config.get("service_noun") or "consultation"
    note = gst_note(config)
    return (
        f"OFFERINGS — the only {noun} options you may sell. Prices are fixed; quote them exactly "
        "as written here and never change, round or invent one:\n" + "\n".join(_offering_lines(packages))
        + (f"\n{note}" if note else "")
    )


def required_details_block(fields: list[dict]) -> str:
    if not fields:
        return "REQUIRED DETAILS: none. The payment link can go out as soon as they have chosen."
    lines = [
        f"- {f['key']}: {f['label']}" + (f" (one of: {', '.join(f['options'])})" if f.get("options") else "")
        for f in fields
    ]
    return (
        "REQUIRED DETAILS to collect before the payment link (the business chose these):\n"
        + "\n".join(lines)
    )


def offering_total(leaf: dict, addons: list[dict]) -> int:
    return leaf["amount_paise"] + sum(a["amount_paise"] for a in addons)


def current_prices(config: dict, session: dict) -> tuple[int, int] | None:
    """(package price, package + add-ons) at the tenant's CURRENT prices, or None when the
    session's offering or one of its add-ons is gone, inactive or unpriced now. The session's
    own amounts are a snapshot from when the offering was chosen and may be out of date."""
    intake = _intake()
    found = intake._find_leaf(intake.normalize_packages(config), session.get("package_key") or "")
    if not found or not found[0].get("active", True) or not (found[0].get("amount_paise") or 0) > 0:
        return None
    leaf = found[0]
    live = {a["key"]: a for a in _active(leaf.get("addons") or [])}
    wanted = [a["key"] for a in session.get("selected_addons") or []]
    if any(k not in live for k in wanted):
        return None
    return leaf["amount_paise"], offering_total(leaf, [live[k] for k in wanted])


def current_charge(config: dict, session: dict) -> int | None:
    """What a payment link for this session charges today: package + add-ons at current
    prices, plus the tenant's GST. None when the offering is gone or unpriced."""
    prices = current_prices(config, session)
    return _intake().charge_paise(prices[1], gst_percent(config)) if prices else None


def price_moved(config: dict, session: dict) -> tuple[int, int] | None:
    """(agreed, now) package + add-ons before GST, when the business changed the price after the
    customer agreed to it (picked the offering, or got a link at it); None when unchanged or
    unknown. A rise needs the customer's yes before a link (create_payment_link enforces it)."""
    prices = current_prices(config, session)
    agreed = session.get("total_amount_paise")
    if not prices or not agreed or prices[1] == agreed:
        return None
    return agreed, prices[1]


def parse_time(value) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def link_is_live(session: dict, current_total: int | None, now: datetime | None = None) -> bool:
    """True only when the stored payment link can still be paid AND is for today's price.
    An unknown expiry (NULL, from before it was recorded) counts as expired."""
    if session.get("status") != AWAITING_PAYMENT_STATUS or not session.get("payment_link"):
        return False
    if not current_total or session.get("amount_paise") != current_total:
        return False
    expires_at = parse_time(session.get("payment_link_expires_at"))
    return expires_at is not None and expires_at - (now or datetime.now(timezone.utc)) > LINK_EXPIRY_MARGIN


def _ist_text(moment: datetime) -> str:
    """'4 Oct, 6:02 PM IST': the time a customer in India reads on their own clock."""
    local = moment.astimezone(IST)
    return f"{local.day} {local:%b}, {local.hour % 12 or 12}:{local:%M} {'AM' if local.hour < 12 else 'PM'} IST"


def away_text(last_seen_at, now: datetime | None = None) -> str | None:
    """'4 days ago' / '5 hours ago' / 'just now'; None when the time is unknown."""
    seen = parse_time(last_seen_at)
    if seen is None:
        return None
    seconds = max(((now or datetime.now(timezone.utc)) - seen).total_seconds(), 0)
    if seconds < 300:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"


def had_link(session: dict) -> bool:
    """A link was made for this deal at some point (cleared on expiry, but its id is kept)."""
    return bool(session.get("payment_link") or session.get("razorpay_payment_link_id"))


def _payment_line(session: dict, link_live: bool = False, now: datetime | None = None) -> str:
    amount = session.get("amount_paise") or session.get("total_amount_paise") or session.get("package_amount_paise")
    if session.get("status") == PAID_STATUS:
        return "PAID"
    if link_live:
        expires = parse_time(session.get("payment_link_expires_at"))
        return f"link sent ({_rupees(amount)}), not paid yet" + (f", valid till {_ist_text(expires)}" if expires else "")
    if session.get("status") == AWAITING_PAYMENT_STATUS and had_link(session):
        expired = parse_time(session.get("payment_link_expires_at"))
        when = f" on {_ist_text(expired)}" if expired and expired <= (now or datetime.now(timezone.utc)) else ""
        return f"the last link expired{when} (or is out of date); a new one will be made if they continue"
    return "not sent"


def _next_step(session: dict, missing: list[str], labels: dict, link_live: bool = False) -> str:
    status = session.get("status")
    if status == PAID_STATUS:
        return "they have paid. Do not sell or send a link; help with anything else and reassure them."
    if link_live:
        return ("the link was already sent. If they want to pay, call create_payment_link to resend "
                "the same link; otherwise just answer them.")
    if missing:
        return f"ask for {labels.get(missing[0], missing[0])} (only after answering anything they asked)."
    if status == AWAITING_PAYMENT_STATUS and had_link(session):
        return ("send the payment link now by calling create_payment_link (the old link is expired or "
                "out of date; a fresh one will be made).")
    return "send the payment link now by calling create_payment_link."


def deal_state_block(config: dict, session: dict | None, *, last_seen_at=None, now: datetime | None = None) -> str:
    """last_seen_at: when the customer last wrote or moved this deal on, read BEFORE this
    message counted (None: the line is left out, e.g. in a mid-turn refresh)."""
    header = "DEAL STATE (facts from the system; trust these over the chat history):"
    if not session or not session.get("package_key"):
        return (
            f"{header}\n- Offering: nothing chosen yet\n- Payment: not sent\n"
            "- Next step: help them choose, but only if they show interest; otherwise just answer them."
        )
    fields = config.get("fields") or []
    collected = session.get("collected_data") or {}
    skipped = session.get("skipped_fields") or []
    prices = current_prices(config, session)
    total = prices[1] if prices else session.get("total_amount_paise") or session.get("package_amount_paise")
    charge = current_charge(config, session)
    link_live = link_is_live(session, charge, now)
    have = "; ".join(f"{k} = {v}" for k, v in collected.items() if v) or "none yet"
    missing = missing_details(fields, collected, skipped)
    labels = {f["key"]: f["label"] for f in fields}
    needed = ", ".join(f"{k} ({labels.get(k, k)})" for k in missing) or "none — ready for the payment link"
    lines = [
        header,
        f"- Offering: {session.get('package_name')} — {_rupees(total)}",
    ]
    away = away_text(last_seen_at, now)
    if away:
        lines.append(f"- Last message from them: {away}")
    lines += [
        f"- Details collected: {have}",
        f"- Details still needed: {needed}",
    ]
    if skipped:
        lines.append(f"- Details the customer could not give: {', '.join(skipped)}")
    lines.append(f"- Payment: {_payment_line(session, link_live, now)}")
    moved = price_moved(config, session) if session.get("status") != PAID_STATUS else None
    if moved and moved[1] > moved[0]:
        lines.append(
            f"- Price changed: they agreed to {_rupees(moved[0])}, it is now {_rupees(moved[1])}. Tell them "
            "the new price and get a clear yes before any link; then call create_payment_link with "
            "customer_agreed_new_price true."
        )
    elif moved:
        lines.append(
            f"- Price changed: it was {_rupees(moved[0])}, it is now {_rupees(moved[1])} (cheaper). "
            "Mention the lower price when you send the link."
        )
    if charge and gst_percent(config):
        lines.append(f"- Payment total with {gst_percent(config):g}% GST: {_rupees(charge)}")
    next_step = _session_next_step(config, session, now)
    if is_returning(session, last_seen_at, now):
        next_step = ("the customer has been away a long time, so the note at the end of this prompt "
                     "decides what to say first.")
    lines.append(f"- Next step: {next_step}")
    return "\n".join(lines)


def _session_next_step(config: dict, session: dict, now: datetime | None = None) -> str:
    """What to do next for an open booking, from the system's facts (no away-time logic)."""
    fields = config.get("fields") or []
    labels = {f["key"]: f["label"] for f in fields}
    missing = missing_details(fields, session.get("collected_data") or {}, session.get("skipped_fields") or [])
    if current_prices(config, session) is None and session.get("status") != PAID_STATUS:
        return ("this offering is not available or not priced any more. Do not send a payment "
                "link; tell them and help them choose something else.")
    link_live = link_is_live(session, current_charge(config, session), now)
    return _next_step(session, missing, labels, link_live)


def _rules_block(config: dict, tapped_key: str | None) -> str:
    noun = config.get("service_noun") or "consultation"
    rules = [
        "Answer the customer's question first, then, only if it helps, move them toward a choice.",
        f"You sell the {noun} right here in this chat. When they ask what you offer, the price, or "
        "whether it is worth it, answer directly from OFFERINGS (name the options and their prices, and "
        "who each suits). Do not send them to an app or website to see prices or to buy these. If "
        "your knowledge says prices or offers are shown in an app, that is a different channel; for "
        "anything in OFFERINGS the price is the one here, and there is no discount unless OFFERINGS shows one.",
        "If DEAL STATE shows a choice already in progress and the customer comes back within a day or "
        "so (a greeting, 'hi'), welcome them back in a few words and continue from exactly where it "
        "stopped: ask for the next missing detail, or offer the link. Do not start over. "
        "But when DEAL STATE says they have been away a long time, this rule does not apply: the note "
        "after these rules decides your whole reply, and a bare greeting or acknowledgement gets only "
        "its question, never a detail request or a link.",
        "Show tappable options with show_options only when they really need to choose. Never "
        "show or list the same options twice in a row (not as buttons and not as a typed list); if "
        "they hesitate or reply vaguely, ask which one in words or recommend one.",
        "When they choose, call select_offering. If that offering has add-ons, ask about them "
        "first and pass addon_keys (an empty list if they want none). If REQUIRED DETAILS is "
        "none and there are no add-ons, call create_payment_link in that same turn, right "
        "after select_offering.",
        "Never ask for a detail the customer already gave anywhere in this chat, even before they "
        "chose; when they choose, save what they already told you straight away. "
        "Collect each required detail from the customer's own words: ask one at a time unless "
        "they give several at once, and call save_details as soon as you have any. If they cannot "
        "or will not answer a detail after you asked, call skip_detail for it.",
        "When DEAL STATE shows nothing is still needed, call create_payment_link in that same "
        "turn. The system attaches the real link; you write only a short lead-in. The same goes "
        "when they ask for the link, say to go ahead or continue, or say a link will not open or "
        "has expired: call create_payment_link (a fresh link is made when the old one is dead or "
        "out of date), do not hand them to a person for that, and never say a link is coming "
        "without calling it.",
        "Never write a payment link, a URL you were not given, or a price that is not in OFFERINGS. "
        "Your knowledge base may still mention older prices or packages; when it disagrees with "
        "OFFERINGS, OFFERINGS is right and the older figure must never be quoted. "
        "Never say a link was sent unless you called create_payment_link and it worked.",
        "If a tool reply says it was refused, do what its message says. Do not pretend it worked.",
        "If they say they paid, that money was deducted, or ask about payment status: call "
        "hand_to_human right away. Never say the payment is confirmed or missing, and do not "
        "point them to an app or a support desk instead.",
        "Also call hand_to_human when they ask for a person or when you cannot answer the same "
        "thing after a second ask. Follow the HANDOVER RULE wording for what you tell them, "
        "once. On later messages do not repeat that line word for word: acknowledge what they "
        "just said in your own words and say the team has been told, without promising a time.",
        "When the customer wants what one of the OFFERINGS gives them (an answer, a reading, a "
        "session), offer that offering right here in this chat with its price. Never send them to an "
        "app, a website or a store for something sold here, even if your description says so.",
        "SOURCE OF TRUTH: OFFERINGS and REQUIRED DETAILS were set by the business on its packages "
        "page and override anything in your description or knowledge that disagrees: the price, "
        "what is sold in this chat, where to buy it, and which details to ask for. If your "
        "description says never to ask for something REQUIRED DETAILS lists, ask for it anyway, "
        f"politely, because it is needed to prepare their {noun}.",
        "Never invent an offering, discount, deadline or policy that is not in your knowledge.",
        f"Never say the {noun} is booked, confirmed or reserved until DEAL STATE shows PAID; before "
        "that, say it gets confirmed once the payment is done. You cannot see a diary or slots, so "
        "never claim a time is free or held.",
        "While a booking is open or after they have paid, show products or photos only if the "
        "customer asks about a product; never push one on your own.",
        "If they clearly say no or ask you to stop, stop selling and close politely in one line. "
        "When the no is an explicit decline of the booking in DEAL STATE ('venam', 'not interested', "
        "'cancel it'), also call close_deal. 'Later', 'will think', 'yosichu solren', a price complaint "
        "or silence are not declines: leave the booking open and answer.",
        "A second, separate booking (another question, one for another person, or a different offering "
        "from the one DEAL STATE shows) while DEAL STATE already shows a booking: call select_offering "
        "with new_booking true, never just re-point the old one; an unpaid old booking is closed for "
        "them, a paid one stays paid. A customer who already paid and wants another booking gets one "
        "the same way, straight away. "
        "Their earlier details (in DEAL STATE, or in a PREVIOUS BOOKING block): show them in "
        "ONE message and ask them to confirm or correct them, and save only what they confirm or "
        "correct. Right after select_offering with new_booking true, that message is your reply: do "
        "not ask for those details afresh and do not send a link yet. Never reuse earlier details "
        "silently, the booking may be for someone else.",
        f"Sound like one real person on WhatsApp: short, warm, use their name once known, "
        f"no bot phrases like 'please select an option'. This is a {noun}, not a form.",
    ]
    text = f"HOW TO SELL THE {noun.upper()}:\n" + "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1))
    if tapped_key:
        text += (
            f"\n\nThe customer just tapped the option with key {tapped_key!r}. Treat that as their choice."
        )
    return text


def is_open_deal(session: dict | None) -> bool:
    """A booking with an offering chosen that is not paid or closed."""
    return bool(session and session.get("package_key") and session.get("status") in OPEN_DEAL_STATUSES)


OPEN_DEAL_STATUSES = frozenset({
    "awaiting_package_choice", "awaiting_addon_choice", COLLECTING_STATUS, CONFIRM_STATUS, AWAITING_PAYMENT_STATUS,
})


def is_returning(session: dict | None, last_seen_at, now: datetime | None = None) -> bool:
    """D4: an open deal and the customer away for a day or more. Only the time and the deal
    are checked here; whether their message already shows intent is the model's judgement."""
    seen = parse_time(last_seen_at)
    return is_open_deal(session) and seen is not None and (now or datetime.now(timezone.utc)) - seen >= RETURN_AFTER


def _return_note(config: dict, session: dict, last_seen_at, now: datetime | None) -> str:
    prices = current_prices(config, session)
    total = prices[1] if prices else session.get("total_amount_paise") or session.get("package_amount_paise")
    offering = f"{session.get('package_name')} ({_rupees(total)})"
    return (
        f"\n\nTHE CUSTOMER IS BACK after {away_text(last_seen_at, now).replace(' ago', '')} away, with "
        f"a booking still open for {offering}. Decide first, by the meaning of their latest message in "
        "whatever language they wrote:\n"
        "A. It shows clear intent: they answer a question, give a detail, pick or name an offering, "
        "ask for the payment link, ask about the price or the service, or decline. Act on it as usual "
        f"(the usual next step: {_session_next_step(config, session, now)}) and do not ask the question in B.\n"
        "B. It does not: a greeting, an acknowledgement, a thank-you, a stray character or an emoji, "
        "or anything you are unsure about. After this long a silence such a message is not an answer "
        "to anything you asked earlier and not a yes to sending the link. Your whole reply is then ONE "
        f"short question, in their language, offering both choices: continue with {offering}, or "
        "something else? In that reply do not ask for any detail, do not mention the payment or the "
        "link, do not list the offerings, and call no tool."
    )


def previous_details_block(config: dict, previous: dict | None) -> str:
    """The details of their earlier, closed booking, offered for confirmation (D6). Never
    reused silently: a repeat customer may be booking for someone else."""
    collected = {k: v for k, v in ((previous or {}).get("collected_data") or {}).items() if v}
    if not collected:
        return ""
    labels = {f["key"]: f.get("label") or f["key"] for f in config.get("fields") or []}
    lines = "; ".join(f"{labels.get(k, k)} = {v}" for k, v in collected.items())
    return (
        f"\n\nPREVIOUS BOOKING (their earlier {(previous or {}).get('package_name') or 'booking'}, now "
        f"closed): {lines}.\nIf they want another booking of any kind (another question, or a new "
        "consultation), your very next message shows these in ONE message and asks them to confirm or "
        "correct them (it may be for someone else); you may ask which offering in the same message. "
        "Do not ask for these details afresh. Save details only after they confirm or correct. "
        "Never reuse them silently."
    )


def deal_prompt(
    config: dict, session: dict | None, *, tapped_key: str | None = None, last_seen_at=None,
    previous_details: dict | None = None, now: datetime | None = None,
) -> str:
    body = "\n\n" + "\n\n".join([
        offerings_block(config),
        required_details_block(config.get("fields") or []),
        deal_state_block(config, session, last_seen_at=last_seen_at, now=now),
        _rules_block(config, tapped_key),
    ]) + "\n"
    body += previous_details_block(config, previous_details)
    if is_returning(session, last_seen_at, now):
        body += _return_note(config, session, last_seen_at, now)
    return body


def handover_tools() -> list[dict]:
    """hand_to_human alone, for replies with no package selling: every business can bring a
    person in, whether or not it sells packages in chat."""
    return [tool for tool in _all_tools({}) if tool["function"]["name"] == TOOL_HAND_TO_HUMAN]


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


def deal_tools(config: dict) -> list[dict]:
    return _all_tools(config)


def _all_tools(config: dict) -> list[dict]:
    packages = _intake().normalize_packages(config)
    keys = [leaf["key"] for leaf in _leaves(packages)]
    fields = config.get("fields") or []
    field_keys = [f["key"] for f in fields]
    key_prop = {"type": "string", "enum": field_keys} if field_keys else {"type": "string"}
    return [
        _tool(
            TOOL_SHOW_OPTIONS,
            "Send the customer tappable buttons or a list of the offerings (or of an offering's "
            "add-ons). Use only when they need to choose. Your text is the message above the options.",
            {
                "of": {"type": "string", "enum": ["packages", "addons"]},
                "under": {"type": "string", "description": "Category key (packages) or offering key (addons). Omit for the top level."},
            },
            ["of"],
        ),
        _tool(
            TOOL_SELECT_OFFERING,
            "Record the offering the customer chose. Price comes from the configuration.",
            {
                "key": {"type": "string", "enum": keys},
                "addon_keys": {"type": "array", "items": {"type": "string"},
                               "description": "Chosen add-on keys. Empty list if none. Required when the offering has add-ons."},
                "new_booking": {"type": "boolean",
                                "description": "true when DEAL STATE already shows a booking in progress and the customer "
                                "wants a second, separate booking (another question, or for another person) or "
                                "picks a different offering from the one shown, or DEAL STATE shows a PAID booking "
                                "and they want another: an unpaid earlier booking is closed, a paid one stays paid, "
                                "and a new one starts. Omit when DEAL STATE shows no booking, or the offering is the "
                                "same one (only its add-ons change)."},
            },
            ["key"],
        ),
        _tool(
            TOOL_SAVE_DETAILS,
            "Save required details the customer just told you, exactly as they said them.",
            {"fields": {
                "type": "object",
                "properties": {k: {"type": "string"} for k in field_keys},
                "additionalProperties": False,
            }},
            ["fields"],
        ),
        _tool(
            TOOL_SKIP_DETAIL,
            "Mark a required detail as not provided when the customer cannot or will not give it.",
            {"key": key_prop, "reason": {"type": "string"}},
            ["key"],
        ),
        _tool(
            TOOL_CREATE_PAYMENT_LINK,
            "Create the payment link for the chosen offering. Takes no amount: the amount is the "
            "chosen offering's price. Refused until every required detail is saved or skipped.",
            {
                "customer_agreed_new_price": {
                    "type": "boolean",
                    "description": "true only when DEAL STATE says the price went up and the customer "
                    "has said yes to the new price in this chat. Omit otherwise.",
                },
            },
        ),
        _tool(
            TOOL_CLOSE_DEAL,
            "Close the customer's open booking. Call it ONLY when they have EXPLICITLY declined it: "
            "'venam', 'not interested', 'cancel it', 'I don't want it'. These are NOT declines, so "
            "do not close: 'later', 'will think', 'yosichu solren', 'let me ask my family', a question "
            "about the price, a complaint that it is costly or a request for a discount (answer it "
            "instead), or silence. If you are not sure it is an explicit decline, do not call "
            "it: the booking stays open. Not for a paid booking.",
            {"reason": {"type": "string", "description": "Their words, briefly."}},
        ),
        _tool(
            TOOL_HAND_TO_HUMAN,
            "Pass this chat to a person on the team.",
            {"reason": {"type": "string"}},
            ["reason"],
        ),
    ]
