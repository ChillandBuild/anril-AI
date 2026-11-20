"""One reply turn of the AI-native deal engine: build the context, ask the model (with the
deal tools alongside the catalog and quick-reply tools), run the tools through
deal_actions, and make the message safe to send.

generate_reply (services/ai_reply.py) calls this for every reply that can use tools: package
selling (WhatsApp, when the tenant has packages), product recommendations and quotes, and
quick-reply blocks all run through the same guarded loop.
The pure prompt and tool schemas are in services/deal_engine.py, the guarded executors in
services/deal_actions.py. Design: docs/plans/ai-native-conversation.md.
"""
import ast
import dataclasses
import difflib
import json
import logging
import re

from app.services import choices, deal_actions, deal_engine, intake

logger = logging.getLogger(__name__)

REPLY_MAX_TOKENS = 600
MAX_ROUNDS = 2
REPEAT_MIN_CHARS = 25
REPEAT_SIMILARITY = 0.9
HANDOVER_LINE_PROBE_CHARS = 40
REPEATED_HANDOVER_REASON = "Anril had no answer for the customer twice in a row"
PAYMENT_COMPLAINT_REASON = "Lead says they paid, asks about payment status, or wants a refund"
HANDOVER_OPENED_NOTE = (
    "\n\nPAYMENT CONCERN — a person on this team has just been alerted to check this customer's "
    "payment or refund request, right here in this chat. Do not approve or refuse a refund yourself. "
    "Your reply must: (1) first acknowledge exactly what they told you, specifically (for example "
    "that they paid and have not heard back), with real empathy and no emoji; (2) say plainly that "
    "the team is checking it and will reply here. Do NOT send them anywhere else (not the app, not a "
    "support desk, not the HANDOVER RULE line): a person here is already on it. Never say the payment "
    "is confirmed or missing, never promise a time, and do not send the exact same sentence you sent "
    "before. If you already told them the team is checking, do not say it again: respond to their new "
    "point specifically (their frustration, their question, the amount they mention), agree where "
    "they are right, and ask for ONE thing that helps the team find it faster if you do not have it "
    "yet (the payment time, the amount, or the UPI/transaction reference or a screenshot)."
)


# "[Payment Link]", "<link>", "[URL]": the model sometimes writes a stand-in for a link it
# was told the system would attach. Code attaches the real one; the stand-in must not reach
# the customer.
_PLACEHOLDER_RE = re.compile(r"\[\s*(?:payment\s+)?(?:link|url)[^\]]*\]|<\s*(?:payment\s+)?(?:link|url)[^>]*>", re.IGNORECASE)


# Payment links are only ever attached by code. A payment URL in the model's own words is
# copied from history (possibly an old link for a different amount) or invented.
_PAYMENT_URL_RE = re.compile(r"https?://(?:[\w-]+\.)*(?:rzp\.io|razorpay\.(?:com|me))\S*", re.IGNORECASE)


_BRACE_PLACEHOLDER_RE = re.compile(r"\{\{\s*[A-Za-z][\w ]*\}\}")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")


def strip_unverified_links(text: str, trusted_text: str) -> tuple[str, list[str]]:
    """(text without invented links, what was removed). A link the model writes must already be in
    the business's own material (trusted_text: the prompt with its knowledge and business details).
    Otherwise it is a guess -- an app-store address, a page that does not exist -- and a customer
    taps it. An unfilled {{PLACEHOLDER}} the model copied from the knowledge goes the same way.
    Links the system attaches itself (payment links, quotes) are added after this check."""
    trusted = {choices.url_key(u) for u in choices.urls_in(trusted_text)}
    removed: list[str] = []

    def drop_markdown(match: re.Match) -> str:
        url = choices.trim_url(match.group(2))
        if choices.url_key(url) in trusted:
            return match.group(0)
        removed.append(url)
        return match.group(1)

    def drop_bare(match: re.Match) -> str:
        url = choices.trim_url(match.group(0))
        if choices.url_key(url) in trusted:
            return match.group(0)
        removed.append(url)
        return match.group(0)[len(url):]  # keep the sentence's own full stop or comma

    cleaned = _MARKDOWN_LINK_RE.sub(drop_markdown, text or "")
    cleaned = choices.URL_RE.sub(drop_bare, cleaned)
    cleaned = _BRACE_PLACEHOLDER_RE.sub(lambda m: removed.append(m.group(0)) or "", cleaned)
    if not removed:
        return text, []
    cleaned = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), removed


def _unverified_link_refusals(removed: list[str]) -> tuple[str, ...]:
    if not removed:
        return ()
    return (
        "You wrote a link that is not in the business information, so it was removed. Never invent, "
        "guess or complete a link or an app-store address. Use only links written in the business "
        "information. If you do not have the link they asked for, say the team will share it here.",
    )


def strip_payment_urls(text: str) -> tuple[str, bool]:
    """(text without payment URLs, whether any was removed)."""
    cleaned, count = _PAYMENT_URL_RE.subn("", text or "")
    if not count:
        return text, False
    return strip_placeholders(cleaned), True


# Grief, illness, anger: a smiley under a condolence reads as a bot. The model does not
# reliably follow the no-emoji rule, so code removes them on these messages.
_SOMBRE_RE = re.compile(
    r"passed away|\bdied\b|\bdeath\b|funeral|\bhospital|\baccident|cancer|\bserious\b|"
    r"\bworst\b|\bcheat|\bfraud|\bscam|\bgarbage\b|\bangry\b|\bdisgust|"
    r"இறந்|மரண|காலமான|இறப்பு",
    re.IGNORECASE,
)
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")


def sombre(message: str) -> bool:
    return bool(_SOMBRE_RE.search(message or ""))


def without_emoji(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", _EMOJI_RE.sub("", text)).replace(" .", ".").strip()


def strip_placeholders(text: str) -> str:
    cleaned = _PLACEHOLDER_RE.sub("", text or "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


_WRITTEN_CALL_RE = re.compile(r"^[ \t]*`*[ \t]*([a-z_][a-z0-9_]*)[ \t]*\((.*)\)[ \t]*`*[ \t]*$", re.MULTILINE)


def _names(calls: list[dict]) -> list[str]:
    return [(c.get("function") or {}).get("name") for c in calls]


def _literal_kwargs(args: str) -> dict | None:
    """of='packages', under="x" -> {"of": "packages", "under": "x"}; None unless every
    argument is a named plain literal."""
    try:
        call = ast.parse(f"f({args})", mode="eval").body
        if call.args or any(kw.arg is None for kw in call.keywords):
            return None
        return {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
    except (SyntaxError, ValueError):
        return None


def written_tool_calls(text: str, tool_names: frozenset[str]) -> tuple[str, list[dict]]:
    """A tool call the model wrote as a line of text ("show_options(of='packages')") instead of
    making it -- live 2026-09-28 on Gemini 3.1 Flash Lite. The line never reaches the customer;
    when its arguments are plain literals it becomes the real call, so it runs through the same
    checks as one the model made."""
    calls: list[dict] = []

    def take(match: re.Match) -> str:
        name = match.group(1)
        if name not in tool_names:
            return match.group(0)
        args = _literal_kwargs(match.group(2))
        if args is not None:
            calls.append({"id": f"written-{len(calls)}", "type": "function",
                          "function": {"name": name, "arguments": json.dumps(args)}})
        return ""

    cleaned = _WRITTEN_CALL_RE.sub(take, text or "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip(), calls


def _known_prices(db, tenant_id: str, lead_id: str) -> frozenset:
    """Every product price (1..10 units) and recent order total for the price guard. The
    catalog block only lists this turn's matching items, so the guard reads all of them."""
    prices: set[float] = set()
    try:
        rows = (
            db.table("catalog_items").select("price_paise")
            .eq("tenant_id", tenant_id).eq("status", "ready").execute()
        ).data or []
        prices |= deal_engine.price_multiples(r.get("price_paise") for r in rows)
    except Exception:
        logger.warning("Catalog price lookup failed for tenant %s", tenant_id)
    prices |= {(d.get("total_paise") or 0) / 100 for d in deal_actions.lead_orders(db, tenant_id, lead_id)}
    return frozenset(p for p in prices if p)


def build_context(
    db, tenant_id: str, lead_id: str, phone: str | None, *,
    channel: str = "whatsapp", catalog: dict | None = None, max_images: int = 0,
) -> deal_actions.DealContext:
    """Always returns a context: every reply runs through the same guards. Package selling
    (DEAL STATE + package tools) is on only for WhatsApp tenants with active packages."""
    try:
        config = intake.get_intake_config(tenant_id, db=db)
    except Exception:
        logger.exception("Intake config read failed for tenant %s -- replying without package tools", tenant_id)
        config = {}
    return deal_actions.DealContext(
        config=config, db=db, lead_id=lead_id, tenant_id=tenant_id, phone=phone or "",
        catalog=dict(catalog or {}), max_images=max_images,
        offerings_enabled=channel == "whatsapp" and deal_engine.is_enabled(config),
        known_prices=_known_prices(db, tenant_id, lead_id),
        buttons_enabled=channel == "whatsapp",
        business_details=_business_details(db, tenant_id),
    )


def _business_details(db, tenant_id: str) -> dict:
    try:
        from app.services.business_details import get_business_details
        return deal_engine.business_detail_values(get_business_details(tenant_id, db))
    except Exception:
        logger.warning("Business details read failed for tenant %s", tenant_id)
        return {}


def pre_turn_guards(ctx: deal_actions.DealContext, message: str) -> bool:
    """Code-level backstop that does not wait for the model: a lead who says they already
    paid, or asks about payment status, gets a person on the case immediately. Returns
    True when a handover was requested."""
    if not deal_engine.is_payment_complaint(message):
        return False
    deal_actions.open_handover(ctx, PAYMENT_COMPLAINT_REASON)
    return True


CAPTURE_LOOKBACK = 6


async def capture_details(
    ctx: deal_actions.DealContext, message: str, *, extractor=None, earlier: list[str] | None = None,
    interactive_id: str | None = None,
) -> dict:
    """Save any required details the customer's message contains, BEFORE the model runs.

    The model is asked to call save_details, but in live tests it sometimes says "noted" and
    never calls it, then asks for the same detail again. This is the code-level backstop: the
    same extractor the old intake flow used, saved through the same guarded save_details
    executor, so the DEAL STATE the model reads already holds what the customer just said.
    Runs only while details are still missing. Never raises. Returns what it newly saved."""
    if not ctx.offerings_enabled:
        return {}
    try:
        session = deal_actions._session(ctx)
        if not session or not session.get("package_key") or session["status"] == deal_engine.PAID_STATUS:
            return {}
        fields = ctx.config.get("fields") or []
        collected = session.get("collected_data") or {}
        if interactive_id and interactive_id.startswith(choices.DETAIL_ID_PREFIX):
            new = _detail_tap_fields(ctx, interactive_id, session)
            if not new:
                return {}
            call = {"function": {"name": deal_engine.TOOL_SAVE_DETAILS, "arguments": json.dumps({"fields": new, "session_id": session["id"]})}}
            outcome = await deal_actions.apply_tool_calls([call], ctx)
            return {} if outcome.refusals else new
        if not deal_engine.missing_details(fields, collected, session.get("skipped_fields") or []):
            return {}
        extract = extractor or intake.extract_fields
        # Details are often given before a package is chosen (no session yet to save them to),
        # so read the customer's recent messages too, not only this one.
        recent = [m for m in (earlier or [])[-CAPTURE_LOOKBACK:] if m] + [message]
        merged = await extract("\n".join(recent), fields, collected, ctx.tenant_id)
        new = {k: v for k, v in merged.items() if v and v != collected.get(k)}
        if not new:
            return {}
        call = {"function": {"name": deal_engine.TOOL_SAVE_DETAILS, "arguments": json.dumps({"fields": new})}}
        await deal_actions.apply_tool_calls([call], ctx)
        return new
    except Exception:
        logger.exception("Detail capture failed for lead %s -- the model will still see the raw message", ctx.lead_id)
        return {}


def _detail_tap_fields(ctx: deal_actions.DealContext, interactive_id: str, session: dict) -> dict:
    tap = choices.parse_detail_tap(interactive_id)
    if not tap or session.get("id") != tap[0] or not session.get("package_key") or session.get("status") == deal_engine.PAID_STATUS:
        return {}
    _, key, value = tap
    field = next((f for f in ctx.config.get("fields") or [] if f["key"] == key), None)
    candidates = [option for option in (field.get("options") or []) if option.strip() == value] if field else []
    if len(candidates) != 1:
        return {}
    return {key: candidates[0]}


def detail_tap_note(ctx: deal_actions.DealContext, interactive_id: str | None) -> str:
    if not interactive_id or not interactive_id.startswith(choices.DETAIL_ID_PREFIX):
        return ""
    if ctx.offerings_enabled and _detail_tap_fields(ctx, interactive_id, _open_session(ctx)):
        return ""
    return (
        "The customer tapped an old or invalid detail button. Its value was not accepted. "
        "Ask for the current booking's missing details again; do not save the value of that old tap."
    )


def without_detail_taps(rows: list[dict]) -> list[dict]:
    return [row for row in rows if not (row.get("interactive_id") or "").startswith(choices.DETAIL_ID_PREFIX)]


INTERACTIVE_BODY_MAX = 1024


async def send_menu(phone: str, body: str, menu: dict, *, tenant_id: str, phone_number_id: str | None = None) -> tuple[str | None, bool]:
    """Send the reply with its choices and return the message ID and whether they were tappable."""
    from app.services import meta_cloud
    from app.services.ai_reply import send_whatsapp

    if len(body) > INTERACTIVE_BODY_MAX:
        await send_whatsapp(phone, body, tenant_id=tenant_id, phone_number_id=phone_number_id)
        body = CHOICE_BODY_FALLBACK
    if menu.get("offering_keys") and tenant_id:
        # Services set to "Send a WhatsApp Form": a package menu becomes the form, which asks
        # package, sub-package, add-ons and details in one go. Any failure sends the menu.
        import asyncio

        from app.services import whatsapp_forms

        form = await asyncio.to_thread(whatsapp_forms.form_for_menu, tenant_id, menu)
        if form:
            try:
                sid = await whatsapp_forms.send_form(phone, body, form, tenant_id=tenant_id, phone_number_id=phone_number_id)
                menu["sent_as_form"] = True
                return sid, True
            except Exception:
                logger.exception("WhatsApp Form send failed -- sending the package menu instead")
    try:
        if menu["kind"] == "buttons":
            data = await meta_cloud.send_interactive_buttons(
                to_number=phone, body_text=body, buttons=menu["buttons"],
                tenant_id=tenant_id, phone_number_id=phone_number_id,
            )
        else:
            data = await meta_cloud.send_list_message(
                to_number=phone, body_text=body, button_text=menu["button_text"], sections=menu["sections"],
                tenant_id=tenant_id, phone_number_id=phone_number_id,
            )
        return (data.get("messages") or [{}])[0].get("id"), True
    except Exception:
        logger.exception("Interactive menu send failed -- falling back to plain text")
        sid = await send_whatsapp(phone, menu_as_text(body, menu), tenant_id=tenant_id, phone_number_id=phone_number_id)
        return sid, False


async def send_link(
    phone: str, link: choices.Link, *, tenant_id: str, phone_number_id: str | None = None, original: str | None = None,
) -> tuple[str | None, bool]:
    """Send the message with its one link as a URL button and return the message ID and whether
    it went as a button. If Meta refuses, the customer gets the original text, link included."""
    from app.services import meta_cloud
    from app.services.ai_reply import send_whatsapp

    try:
        data = await meta_cloud.send_cta_url_message(
            to_number=phone, body_text=link.body or CHOICE_BODY_FALLBACK, button_text=link.label,
            button_url=link.url, tenant_id=tenant_id, phone_number_id=phone_number_id,
        )
        return (data.get("messages") or [{}])[0].get("id"), True
    except Exception:
        logger.exception("URL button send failed -- falling back to plain text")
        sid = await send_whatsapp(
            phone, original or f"{link.body}\n{link.url}".strip(), tenant_id=tenant_id, phone_number_id=phone_number_id,
        )
        return sid, False


def menu_as_text(body: str, menu: dict) -> str:
    return body + "\n\n" + "\n".join(f"• {title}" for title in menu["options"])


def menu_log_text(body: str, menu: dict) -> str:
    return body + "\n\n" + "  ".join(f"[{title}]" for title in menu["options"])


def menu_record(body: str, menu: dict, *, tappable: bool) -> str:
    """Record button tags only for choices sent as an interactive message."""
    if menu.get("sent_as_form"):
        from app.services.whatsapp_forms import form_record
        return form_record(body)
    return menu_log_text(body, menu) if tappable else menu_as_text(body, menu)


def _last_assistant_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return message.get("content") or ""
    return ""


def _state_line(ctx: deal_actions.DealContext) -> str:
    if not ctx.offerings_enabled:
        return ""
    try:
        return deal_engine.deal_state_block(ctx.config, deal_actions._session(ctx))
    except Exception:
        logger.exception("Deal state refresh failed for lead %s", ctx.lead_id)
        return ""


def _last_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _price_refusals(text: str, ctx: deal_actions.DealContext, customer_message: str) -> tuple[str, ...]:
    wrong = deal_engine.unknown_prices(text, ctx.config, customer_message, ctx.known_prices)
    if not wrong:
        return ()
    shown = ", ".join(f"₹{p:g}" for p in wrong)
    return (
        f"Your draft quotes {shown}, which is not a current price (OFFERINGS, CATALOG or ORDERS). "
        "Quote only those prices, or leave the price out.",
    )


REPEAT_LOOKBACK = 3


def _repeat_refusals(text: str, earlier: list[str]) -> tuple[str, ...]:
    """A long reply that is (nearly) word for word one of the last few sent reads like a bot."""
    a = text.strip().lower()
    if len(a) < REPEAT_MIN_CHARS:
        return ()
    recent = [t.strip().lower() for t in earlier[-REPEAT_LOOKBACK:] if t.strip()]
    if not any(difflib.SequenceMatcher(None, a, b).ratio() >= REPEAT_SIMILARITY for b in recent):
        return ()
    return (
        "You already said this in your previous message, nearly word for word. Say something "
        "different: respond to what they just wrote, specifically.",
    )


def _bare_handover_refusals(draft: str, handover_line: str, handover_opened: bool) -> tuple[str, ...]:
    """After a payment concern, a reply that is only the client's stock help line ignores what
    the customer said. It must acknowledge them first."""
    if not handover_opened or not _said_handover_line(draft, handover_line):
        return ()
    return (
        "Do not send them to the stock help line: a person on this team is already checking their "
        "payment here. Acknowledge what they told you and say the team is checking it and will reply "
        "in this chat.",
    )


# "I'm checking with my team" is only true if a person was alerted: code makes it true.
_TEAM_CHECKING_RE = re.compile(
    r"\b(checking with|check with|asking|informing|informed|alerting|alerted|passing (?:this|it) (?:on|to)|"
    r"looping in|bringing in|notif\w+)\b[^.?!\n]{0,30}\b(team|colleague|owner|manager|staff)\b"
    r"|\b(team|colleague|owner|manager|staff)\b[^.?!\n]{0,40}\b(will|shall|going to)\b[^.?!\n]{0,30}"
    r"\b(reply|respond|get back|check|look into|message|call|contact)\w*"
    r"|\bteam\s*(?:kitta|kitte|ku)\b",
    re.IGNORECASE,
)
# "I've checked with the team, they said..." -- only a person can report that.
_TEAM_ANSWERED_RE = re.compile(
    r"\b(i(?:'ve| have)? (?:checked|confirmed|spoken|talked|asked) with (?:the|my|our) (?:team|owner|manager|staff)"
    r"|(?:the|my|our) (?:team|owner|manager|staff) (?:has |have )?(?:said|says|confirmed|told me|replied|checked))\b",
    re.IGNORECASE,
)
TEAM_CLAIM_REASON = "Anril told the customer it is checking with the team"
ASKED_AGAIN_SIMILARITY = 0.6
# How Anril says it has no answer, in the languages seen in production.
_NO_ANSWER_RE = re.compile(
    r"\b(don'?t (?:have|know)|do not (?:have|know)|not sure|no (?:information|details)|couldn'?t find|"
    r"theriyala|theriyadhu|illa(?:\s+info)?|therila)\b|தெரியவில்லை|தகவல் இல்லை",
    re.IGNORECASE,
)
TEAM_ALERTED_NOTE = (
    "\n\nA PERSON HAS BEEN ALERTED: the customer asked the same thing again and you had no answer "
    "last time, so a person on this team has just been alerted and will reply in this chat. Do "
    "not guess or invent an answer. Acknowledge their question and say the team will reply here, "
    "without promising a time."
)


def _asked_again(messages: list[dict], handover_line: str) -> bool:
    """The customer repeats a question Anril could not answer: a person, not a third try."""
    users = [m.get("content") or "" for m in messages if m.get("role") == "user"]
    assistants = _earlier_assistant_texts(messages)
    if len(users) < 2 or not assistants:
        return False
    now, before = users[-1].strip().lower(), users[-2].strip().lower()
    if not now or difflib.SequenceMatcher(None, now, before).ratio() < ASKED_AGAIN_SIMILARITY:
        return False
    answer = assistants[-1]
    return bool(_NO_ANSWER_RE.search(answer)) or _said_handover_line(answer, handover_line)


_DETAIL_NAMES = {"gstin": "GST number", "email": "email address", "phone": "phone number", "address": "address"}


def _business_detail_refusals(text: str, ctx: deal_actions.DealContext, customer_message: str) -> tuple[str, ...]:
    shared = deal_engine.volunteered_details(text, ctx.business_details, customer_message)
    if not shared:
        return ()
    names = ", ".join(_DETAIL_NAMES[k] for k in shared)
    return (f"Do not share the business's {names}: the customer did not ask for it. Leave it out.",)


def _team_answer_refusals(text: str) -> tuple[str, ...]:
    if not _TEAM_ANSWERED_RE.search(text or ""):
        return ()
    return (
        "You have not heard back from the team, so never say they checked, said or confirmed "
        "anything. If you do not know the answer, say so honestly and call hand_to_human.",
    )


def _payment_url_refusals(removed_url: bool, attached: "_Attached") -> tuple[str, ...]:
    """The model wrote a payment link itself. If code attached a real one this turn, dropping the
    model's copy is enough; otherwise its words promise a link that will not be there."""
    if not removed_url or attached.link or attached.quote:
        return ()
    return (
        "Do not write any payment link yourself; links are attached by the system only. If they "
        "want to pay, call create_payment_link (packages) or send_quote (products); otherwise do not "
        "mention a link.",
    )


def _earlier_assistant_texts(messages: list[dict]) -> list[str]:
    return [m.get("content") or "" for m in messages if m.get("role") == "assistant"]


def _repeated_line_refusals(draft: str, handover_line: str, line_said_before: bool) -> tuple[str, ...]:
    if not line_said_before or not _said_handover_line(draft, handover_line):
        return ()
    return (
        "You already gave the customer the help line earlier in this chat; do not repeat it. A "
        "person on the team has now been asked to help. Respond to what they just wrote, in your "
        "own words, and tell them the team will get back to them (no time promised).",
    )


def _said_handover_line(text: str, handover_line: str) -> bool:
    probe = handover_line.strip().lower()[:HANDOVER_LINE_PROBE_CHARS]
    return bool(probe) and probe in text.lower()


class _Attached:
    """What the system will send along with the words, accumulated across rounds."""

    def __init__(self):
        self.menu: dict | None = None
        self.link: str | None = None
        self.quote: str | None = None
        self.images: list[str] = []
        self.handover = False

    def add(self, outcome: deal_actions.Outcome) -> None:
        self.menu = outcome.menu or self.menu
        self.link = outcome.payment_link or self.link
        self.quote = outcome.quote_text or self.quote
        self.images += [i for i in outcome.image_item_ids if i not in self.images]
        self.handover = self.handover or outcome.handover

    def any(self) -> bool:
        return bool(self.menu or self.link or self.quote or self.images)

    def notes(self, ctx: deal_actions.DealContext) -> list[str]:
        lines = []
        if self.menu:
            lines.append("The tappable options are already attached; do not call show_options again.")
        if self.link:
            lines.append("The payment link is already created and will be attached; do not write any link.")
        if self.quote:
            lines.append("The itemised quote with its payment link will be attached after your words; do not repeat the prices or write any link.")
        if self.images:
            names = ", ".join((ctx.catalog.get(i) or {}).get("name", i) for i in self.images)
            lines.append(f"Photos of {names} will be sent after your message.")
        if self.handover:
            lines.append(
                "A person on the team has been alerted and will reply in this chat. Tell the "
                "customer so, following the HANDOVER RULE, without promising a time."
            )
        return lines

    def outcome(self, refusals: tuple[str, ...]) -> deal_actions.Outcome:
        return deal_actions.Outcome(
            self.menu, self.link, refusals, self.handover, self.quote, tuple(self.images),
        )


def _round_note(ctx: deal_actions.DealContext, refusals: tuple[str, ...], attached: _Attached, *, text_only: bool = False) -> str:
    lines = ["[System note, not from the customer]"]
    if refusals:
        lines.append("The system refused part of your last reply:")
        lines.extend(f"- {r}" for r in refusals)
    else:
        lines.append("Your actions were applied.")
    lines.append(_state_line(ctx))
    lines.extend(attached.notes(ctx))
    ask = (
        "Now write the message to send to the customer: same language and tone, claim nothing "
        "that was refused, and ask for any detail still needed."
    )
    if text_only:
        lines.append(f"{ask} Do not call any tool and do not write any link. Output only the message.")
    elif ctx.offerings_enabled:
        lines.append(f"{ask} If nothing is still needed and no payment link exists yet, call create_payment_link. Output only the message.")
    else:
        lines.append(f"{ask} Output only the message.")
    return "\n".join(line for line in lines if line)


async def _final_text(messages, ctx, refusals, attached, tenant_id, llm) -> str:
    """Tool rounds can end with no words at all (this provider writes no text on a turn where it
    calls a tool). One last call with no tools offered, only to say what just happened."""
    final = [
        *messages,
        {"role": "assistant", "content": "(no text)"},
        {"role": "user", "content": _round_note(ctx, refusals, attached, text_only=True)},
    ]
    try:
        return strip_payment_urls(strip_placeholders(await llm(final, max_tokens=REPLY_MAX_TOKENS, tenant_id=tenant_id)))[0]
    except Exception:
        logger.exception("Deal reply final text call failed for lead %s", ctx.lead_id)
        return ""


async def converse_once(
    chat_messages: list[dict],
    other_tools: list[dict],
    ctx: deal_actions.DealContext,
    *,
    tenant_id: str,
    llm_with_tools=None,
    llm=None,
    append_link: bool = True,
    handover_opened: bool = False,
    handover_line: str = "",
) -> tuple[str, list[dict], deal_actions.Outcome]:
    """(reply text, the model's tool calls, what to attach).

    One model call in the normal case. A second round runs only when the model wrote no
    text, or the system refused something (a tool, a price not in the catalog/offerings, a
    near-repeat of the last message): the model is shown what happened and the fresh DEAL
    STATE, and may write the message or make the next call (e.g. create_payment_link right
    after select_offering). If the words are still missing, one tool-free call writes them.

    The package payment link is appended by code after the text (append_link=False lets the
    caller do it after its own post-processing). A product quote's text and link are in
    outcome.quote_text for the caller to append the same way."""
    if llm_with_tools is None or llm is None:
        from app.services import ai_reply
        llm_with_tools = llm_with_tools or ai_reply._llm_chat_with_tools
        llm = llm or ai_reply._llm_chat
    tools = (
        (deal_engine.deal_tools(ctx.config) if ctx.offerings_enabled else deal_engine.handover_tools())
        + [choices.tool_def()] + list(other_tools)
    )
    tool_names = frozenset((t.get("function") or {}).get("name") for t in tools) - {None}
    offered: list[str] = []
    choice_args: dict = {}
    last_text = _last_assistant_text(chat_messages)
    customer_message = _last_user_text(chat_messages)
    # Links the model may repeat: those in the prompt (knowledge, business details) and in the
    # business's own settings. Earlier replies are not trusted: a bad link would repeat itself.
    system_prompt = chat_messages[0].get("content") or "" if chat_messages and chat_messages[0].get("role") == "system" else ""
    trusted_text = "\n".join([system_prompt, *(
        json.dumps(source, default=str, ensure_ascii=False) for source in (ctx.business_details, ctx.catalog, ctx.config)
    )])
    line_said_before = any(_said_handover_line(t, handover_line) for t in _earlier_assistant_texts(chat_messages))
    wanted_line_again = False
    messages = list(chat_messages)
    if handover_opened:
        ctx = dataclasses.replace(ctx, payment_concern=True)
    if handover_opened and messages and messages[0].get("role") == "system":
        messages[0] = {**messages[0], "content": messages[0]["content"] + HANDOVER_OPENED_NOTE}
    all_calls: list[dict] = []
    attached = _Attached()
    if not handover_opened and _asked_again(messages, handover_line):
        deal_actions.open_handover(ctx, REPEATED_HANDOVER_REASON)
        attached.handover = True
        if messages and messages[0].get("role") == "system":
            messages[0] = {**messages[0], "content": messages[0]["content"] + TEAM_ALERTED_NOTE}
    text = ""
    refusals: tuple[str, ...] = ()
    text_only = not tools
    for attempt in range(MAX_ROUNDS):
        try:
            if text_only:
                # No tools, or every action is done and only the words are missing: offer no
                # tools, so the model cannot answer with yet another silent tool call.
                draft, calls = await llm(messages, max_tokens=REPLY_MAX_TOKENS, tenant_id=tenant_id), []
            else:
                draft, calls = await llm_with_tools(
                    messages, tools=tools, max_tokens=REPLY_MAX_TOKENS, tenant_id=tenant_id,
                )
        except Exception:
            if attempt == 0:
                raise
            logger.exception("Deal reply second round failed -- keeping what we have")
            break
        draft, written = written_tool_calls(draft, tool_names)
        made = {(c.get("function") or {}).get("name") for c in calls}
        written = [c for c in written if c["function"]["name"] not in made]
        if written:
            logger.info("Model wrote %s as text for lead %s -- running it as the call", _names(written), ctx.lead_id)
            calls = [*calls, *written]
        offered = []
        from_tool = choices.from_tool_calls(calls)
        if from_tool:
            message, offered = from_tool
            draft = message or draft
        choice_args = _choice_args(calls)
        if choice_args:
            draft = str(choice_args.get("message") or "") or draft
        draft, removed_url = strip_payment_urls(strip_placeholders(draft))
        draft, invented_links = strip_unverified_links(draft, trusted_text)
        if attempt == 0 and line_said_before and _said_handover_line(draft, handover_line):
            # The model reached for the "I can't help" line a second time: it has nothing
            # more to offer here. Bring a person in; the message itself gets rewritten below.
            wanted_line_again = True
        text = draft or text
        all_calls.extend(calls)
        outcome = (
            deal_actions.Outcome() if not calls
            else await deal_actions.apply_tool_calls(
                calls, ctx, last_assistant_text=last_text, auto_link=True, customer_message=customer_message,
            )
        )
        attached.add(outcome)
        if attached.menu and attached.menu.get("choice_bound"):
            attached.menu = None
        choice_menu, choice_refusal = _configured_menu(ctx, choice_args, offered or choices.extract(draft)[1], body=draft)
        if choice_menu:
            choice_menu["choice_bound"] = True
            attached.menu = choice_menu
        refusals = (
            *outcome.refusals,
            *((choice_refusal,) if choice_refusal else ()),
            *_price_refusals(draft, ctx, customer_message),
            *_repeat_refusals(draft, _earlier_assistant_texts(chat_messages)),
            *_bare_handover_refusals(draft, handover_line, handover_opened),
            *_repeated_line_refusals(draft, handover_line, line_said_before),
            *_payment_url_refusals(removed_url, attached),
            *_unverified_link_refusals(invented_links),
            *_team_answer_refusals(draft),
            *_business_detail_refusals(draft, ctx, customer_message),
        )
        if draft and not refusals:
            break
        text_only = not tools or (attached.any() and not refusals and not draft)
        if attempt < MAX_ROUNDS - 1:
            messages = [
                *messages,
                {"role": "assistant", "content": draft or "(no text)"},
                {"role": "user", "content": _round_note(ctx, refusals, attached)},
            ]
    if not text:
        text = await _final_text(messages, ctx, refusals, attached, tenant_id, llm)
    text, _ = written_tool_calls(text, tool_names)  # the tool-free last call can write one too
    text, _ = strip_payment_urls(text)
    text, _ = strip_unverified_links(text, trusted_text)
    if sombre(customer_message) or handover_opened or attached.handover:
        text = without_emoji(text)  # a person is being brought in: no smileys
    if refusals and deal_engine.unknown_prices(text, ctx.config, customer_message, ctx.known_prices):
        logger.warning("Reply still quotes a price outside the catalog/offerings for lead %s", ctx.lead_id)
    if wanted_line_again and not attached.handover:
        deal_actions.open_handover(ctx, REPEATED_HANDOVER_REASON)
        attached.handover = True
    if not attached.handover and _TEAM_CHECKING_RE.search(text):
        deal_actions.open_handover(ctx, TEAM_CLAIM_REASON)
        attached.handover = True
    text = _attach_choices(text, ctx, attached, offered, last_text, customer_message, choice_args)
    if not refusals:
        await _classify_choices(text, ctx, attached, customer_message, llm, tenant_id)
    _label_list(attached, text, customer_message, choice_args)
    if attached.link and append_link:
        text = f"{text}\n{attached.link}".strip()
    return text, all_calls, attached.outcome(refusals)


CHOICE_BODY_FALLBACK = "👇"
CHOICE_CLASSIFY_TIMEOUT = 2.5  # seconds; the safety net never holds a reply longer than this


async def _classify_choices(
    text: str, ctx: deal_actions.DealContext, attached: _Attached, customer_message: str, llm, tenant_id: str,
) -> None:
    """The safety net: a reply that asks a question but matched no choice pattern is read by one
    small timed call, so a pick written in any language still gets its buttons. Statements,
    replies that already carry a menu or a payment link, and channels without buttons skip it."""
    if (attached.menu or attached.link or attached.quote or attached.handover or not ctx.buttons_enabled
            or not choices.might_offer_choice(text)):
        return
    found = await choices.classify(text, customer_message, llm, tenant_id, timeout=CHOICE_CLASSIFY_TIMEOUT)
    if found:
        options, label = found
        attached.menu = choices.build_menu(options, label)


def _label_list(attached: _Attached, text: str, customer_message: str, choice_args: dict) -> None:
    """The bar that opens a list says "View options" in the customer's language: the model's own
    wording when it gave one, else by script or Tanglish, else English."""
    menu = attached.menu
    if menu and menu.get("kind") == "list":
        hint = choice_args.get("list_label") or (menu["button_text"] if menu.get("label_from_model") else "")
        menu["button_text"] = choices.list_label_for(f"{customer_message}\n{text}", hint=hint)


def _attach_choices(
    text: str, ctx: deal_actions.DealContext, attached: _Attached, offered: list[str], last_text: str,
    customer_message: str = "",
    choice_args: dict | None = None,
) -> str:
    """Options offered in words always go out tappable (services/choices.py). In order: a
    package menu from show_options, offer_choices, a CHOICES line or a typed list, a question
    naming two or more packages, a question about a detail with fixed options, options
    written inline in the question ("Morning, Afternoon or Evening?")."""
    body, options = choices.extract(text)
    if attached.menu and not attached.menu.get("field_key") and not _menu_fits(body, attached.menu, ctx):
        # show_options under a message about something else ("your name and a time?"): the
        # buttons would not answer the question, so drop them and look for the real options.
        logger.info("Dropped a package menu that did not match the message for lead %s", ctx.lead_id)
        attached.menu = None
    if attached.menu:
        body = _explain_menu(body, attached.menu, ctx)
        if not ctx.buttons_enabled or attached.menu["kind"] == "text":
            options = attached.menu["options"]
            attached.menu = None
            return choices.as_text(body, options)
        return body
    options = offered or options
    menu, refusal = _configured_menu(ctx, choice_args or {}, options, body=body)
    if menu:
        body = _explain_menu(body, menu, ctx)
        if not ctx.buttons_enabled or menu["kind"] == "text":
            return choices.as_text(body, menu["options"])
        attached.menu = menu
        return body
    if refusal:
        return body
    if not options and ctx.buttons_enabled:
        attached.menu, just_shown = _package_menu(body, ctx, last_text, customer_message)
        if attached.menu or just_shown:
            return _explain_menu(body, attached.menu, ctx) if attached.menu else body
    options = options or _detail_options(body, ctx) or choices.inline_options(body) or choices.yes_no_options(body)
    if not options:
        return body
    if not ctx.buttons_enabled:
        return choices.as_text(body, options)
    menu, refusal = _configured_menu(ctx, {}, options, body=body)
    if refusal:
        return body
    if menu and menu["kind"] == "text":
        return choices.as_text(body, menu["options"])
    attached.menu = menu or choices.build_menu(options)
    return body or CHOICE_BODY_FALLBACK


def _choice_args(calls: list[dict]) -> dict:
    for call in calls:
        func = call.get("function") or {}
        if func.get("name") == choices.TOOL_NAME:
            try:
                args = json.loads(func.get("arguments") or "{}")
            except (ValueError, TypeError):
                return {}
            return args if isinstance(args, dict) else {}
    return {}


def _offering_levels(ctx: deal_actions.DealContext) -> list[list[dict]]:
    levels = []

    def walk(nodes):
        active = deal_engine._active(nodes)
        if active:
            levels.append(active)
        for node in active:
            walk(node.get("options") or [])
            walk(node.get("addons") or [])

    walk(intake.normalize_packages(ctx.config))
    return levels


def _option_name(text: str) -> str:
    return re.sub(r"\s*\((?:₹\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*(?:Rs\.?|INR|₹))\)\s*$", "", text, flags=re.I).strip().casefold()


def _configured_menu(
    ctx: deal_actions.DealContext, args: dict, options: list[str], *, body: str | None = None,
) -> tuple[dict | None, str]:
    explicit = "field_key" in args or "offering_keys" in args
    refused = "offer_choices refused: use a valid configured offering or an unanswered choice field from this booking."
    if not ctx.offerings_enabled:
        return None, refused if explicit else ""
    if sum(key in args for key in ("field_key", "offering_keys", "options")) > 1:
        return None, refused
    if "offering_keys" in args or options and "field_key" not in args:
        keys = args.get("offering_keys")
        if "offering_keys" in args and (not isinstance(keys, list) or len(keys) < 2 or any(not isinstance(k, str) for k in keys)):
            return None, refused
        matches = []
        for level in _offering_levels(ctx):
            selected = []
            for option in keys if keys is not None else options:
                found = [n for n in level if n["key"] == option] if keys is not None else [
                    n for n in level if _option_name(option) in {
                        n["key"].casefold(), n["name"].casefold(), (n.get("button_label") or "").casefold(),
                    }
                ]
                if len(found) != 1:
                    break
                selected.append(found[0])
            else:
                if len(selected) >= 2 and len({n["key"] for n in selected}) == len(selected):
                    matches.append(selected)
        if len(matches) == 1:
            menu = deal_actions.build_level_menu(matches[0])
            if menu:
                menu["offering_keys"] = [n["key"] for n in matches[0]]
                if body is not None and not _menu_fits(body, menu, ctx):
                    return None, "offer_choices refused: the message asks for a detail, but these options select offerings. Explain the offerings and ask the customer to choose one."
                return menu, ""
        if keys is not None:
            return None, refused
    session = _open_session(ctx)
    if not session.get("package_key") or session.get("status") == deal_engine.PAID_STATUS:
        return None, refused if explicit else ""
    fields = ctx.config.get("fields") or []
    missing = deal_engine.missing_details(fields, session.get("collected_data") or {}, session.get("skipped_fields") or [])
    candidates = [f for f in fields if (f["key"] in missing or "field_key" in args) and f.get("options") and (
        f["key"] == args.get("field_key") if "field_key" in args else
        len(options) >= 2 and {o.casefold() for o in options} == {o.casefold() for o in f["options"]}
    )]
    if len(candidates) == 1 and session.get("id"):
        menu = choices.build_detail_menu(candidates[0], session["id"])
        menu = menu or {"kind": "text", "options": candidates[0]["options"]}
        menu["field_key"] = candidates[0]["key"]
        return menu, ""
    return None, refused if explicit else ""


def _explain_menu(body: str, menu: dict, ctx: deal_actions.DealContext) -> str:
    keys = menu.get("offering_keys") or []
    if not keys:
        return body
    nodes = {n["key"]: n for level in _offering_levels(ctx) for n in level}
    missing = [nodes[k] for k in keys if k in nodes and nodes[k]["name"].casefold() not in body.casefold()]
    if not missing:
        return body
    summary = []
    for node in missing:
        line = node["name"]
        if not node.get("options"):
            line += f" — {intake._rupees(node['amount_paise'])}"
        summary.append(line)
    return (body + "\n\n" + "\n".join(summary)).strip()


def _detail_options(text: str, ctx: deal_actions.DealContext) -> list[str]:
    fields = ctx.config.get("fields") or []
    if not ctx.offerings_enabled or not any(f.get("options") for f in fields):
        return []
    session = _open_session(ctx)
    if not session.get("package_key"):
        return []
    missing = deal_engine.missing_details(fields, session.get("collected_data") or {}, session.get("skipped_fields") or [])
    matches = [choices.field_options_for(text, f) for f in fields if f["key"] in missing]
    matches = [m for m in matches if m]
    return matches[0] if len(matches) == 1 else []


PACKAGE_MENTION_MIN = 2
_COMPARE_RE = re.compile(r"\b(difference|differ|compare|vs|versus|better|which one|or)\b|வித்தியாசம்", re.IGNORECASE)


def _offering_names(ctx: deal_actions.DealContext) -> list[str]:
    from app.services import intake

    nodes = intake.normalize_packages(ctx.config)
    names: list[str] = []

    def walk(level):
        for n in deal_engine._active(level):
            names.extend(x for x in (n.get("name"), n.get("button_label")) if x)
            walk(n.get("options") or [])
    walk(nodes)
    return names


def _menu_fits(body: str, menu: dict, ctx: deal_actions.DealContext) -> bool:
    """A package menu belongs under a message that is about the offerings: it names one, speaks
    of options/packages, or has no question of its own ("Here's what we have 👇")."""
    lowered = body.lower()
    question = _last_question(body)
    if not question:
        return True
    if any(t.lower() in lowered for t in [*menu.get("options", []), *_offering_names(ctx)]):
        return True
    if _OFFER_QUESTION_RE.search(body):
        return True
    # "Which one suits you?" picks from the menu; "Morning, afternoon or evening?" picks something else.
    return bool(choices.PICK_CUE_RE.search(question)) and not choices.inline_options(body)



def _open_session(ctx: deal_actions.DealContext) -> dict:
    """The lead's booking row, or {} -- a read failure must not cost the customer the reply."""
    try:
        return deal_actions._session(ctx) or {}
    except Exception:
        logger.warning("Session read failed for lead %s while attaching options", ctx.lead_id)
        return {}
# "Want to see the options?" -- asking whether to show them is showing them.
_OFFER_QUESTION_RE = re.compile(r"\b(options?|packages?|plans?|prices?|pricing)\b", re.IGNORECASE)


# "1200/-" is how Indian price lists write rupees.
_SLASH_DASH_AMOUNT_RE = re.compile(rf"({deal_engine._NUMBER})\s*/-")


def _mentions(lowered: str, phrase: str | None) -> bool:
    """Whole-word match: plan "Pro" is not in "process", and an empty label matches nothing."""
    phrase = (phrase or "").strip().lower()
    return bool(phrase) and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered) is not None


def _names_quoted(text: str, level: list[dict]) -> int:
    lowered = text.lower()
    return sum(1 for n in level if _mentions(lowered, n.get("name")) or _mentions(lowered, n.get("button_label")))


def _prices_quoted(text: str, level: list[dict]) -> int:
    """How many distinct offering prices the text quotes as rupee amounts (₹99, Rs.99, 99 rupees,
    99/-). A bare number ("199 astrologers") is not a price."""
    catalog = {n["amount_paise"] / 100 for n in level if n.get("amount_paise")}
    found = (
        deal_engine._AMOUNT_BEFORE_RE.findall(text)
        + deal_engine._AMOUNT_AFTER_RE.findall(text)
        + _SLASH_DASH_AMOUNT_RE.findall(text)
    )
    return len(catalog & {deal_engine._to_float(a) for a in found})


def _menu_levels(packages: list[dict]) -> list[list[dict]]:
    """Every level a customer can pick from: the top level first, then each category's options."""
    levels: list[list[dict]] = []

    def walk(nodes: list[dict]) -> None:
        active = deal_engine._active(nodes)
        if active:
            levels.append(active)
        for node in active:
            if node.get("options"):
                walk(node["options"])

    walk(packages)
    return levels


def _listed_level(text: str, ctx: deal_actions.DealContext) -> list[dict] | None:
    """The one level whose offerings the text lays out -- 2+ of them by name or by price --
    the most-mentioned level winning, the top level on a tie. None when no level is laid out."""
    best, best_score = None, PACKAGE_MENTION_MIN - 1
    for level in _menu_levels(intake.normalize_packages(ctx.config)):
        score = max(_names_quoted(text, level), _prices_quoted(text, level))
        if score > best_score:
            best, best_score = level, score
    return best


def _asks_for_detail(question: str, ctx: deal_actions.DealContext) -> bool:
    """The question asks for one of the business's required details ("may I have your full name?")."""
    lowered = question.lower()
    return any(_mentions(lowered, f.get("label")) for f in ctx.config.get("fields") or [])


def _last_question(text: str) -> str:
    found = re.findall(r"[^.!?？\n]*[?？]", text or "")
    return found[-1] if found else ""



def _package_menu(
    text: str, ctx: deal_actions.DealContext, last_text: str, customer_message: str = "",
) -> tuple[dict | None, bool]:
    """(menu, just_shown). A message that lays out two or more of the offerings, or a question
    that asks whether to show them, gets them as buttons -- only while nothing is chosen yet,
    and not when that very menu was just sent and the customer's reply was vague (just_shown)."""
    question = _last_question(text)
    comparing_now = bool(_COMPARE_RE.search(customer_message or ""))
    if not ctx.offerings_enabled:
        return None, False
    # Two or more offerings laid out, by name or by price: the customer can only answer "which
    # one?". No question mark and no "which" word is required -- the model says it a different way
    # every time ("Edhu venum-nu sollunga", "எதை..."), often as a request rather than a question,
    # and a price reads the same in every language even when the model translates the names.
    listed = _listed_level(text, ctx)
    if not (question or comparing_now or listed is not None):
        return None, False
    comparing = comparing_now
    session = _open_session(ctx)
    if session.get("package_key") and session.get("status") != deal_engine.PAID_STATUS and not comparing:
        return None, False  # mid-booking: the question is about a detail, not the packages
    if listed is not None and question and _asks_for_detail(question, ctx):
        return None, False  # "Basic is ₹999, Pro ₹1,999 -- may I have your full name?"
    if listed is not None:  # "what's the difference between 49 and 99?", or just the packages laid out
        menu = deal_actions.build_level_menu(listed)
    elif _OFFER_QUESTION_RE.search(question):
        _level, menu = deal_actions.top_level_menu(ctx)
    else:
        return None, False
    if menu is None:
        return None, False
    if last_text and all(f"[{title}]" in last_text for title in menu["options"]) and choices.is_vague(customer_message):
        return None, True
    return menu, False
