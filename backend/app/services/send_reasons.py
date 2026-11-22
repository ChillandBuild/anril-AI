"""One place that turns "why didn't this message go out" into plain words.

Merges what used to live in three places: auto_messages._PLAIN_META_FAILURES (live send
failures), upload._META_CODE_REASONS (broadcast failure buckets) and the frontend's
auto-messages/shared.ts META_CODE_TEXT + REASON_TEXT, and adds the codes Meta reports
asynchronously through the delivery webhook (131047, 131049, 131048, 131050, 131042).

explain(raw) takes whatever a log row holds: Meta's raw JSON error, a "(#131047)" blurb,
a short code like "opted_out", or a sentence that is already plain, and returns
{text, kind, code}. `kind` drives the "what to do" link on the Sent page:
  undeliverable  the number isn't on WhatsApp
  template       the template isn't approved / paused / missing / its values don't match
  stopped        they said stop, turned marketing off, or the person is blocked
  window         more than 24 hours since their last message, needs a template
  retry          WhatsApp slowed it down; nothing to do
  other          anything else (open the chat)
"""
import re

UNKNOWN = "WhatsApp didn't send it"

# Meta error codes -> plain words. The first nine are the live-send wording that
# auto_messages._plain_failure has always used: those sentences must not change.
META_CODE_TEXT: dict[str, str] = {
    "131026": "WhatsApp couldn't deliver to this number. Check that it is on WhatsApp.",
    "131030": "This number isn't on your WhatsApp test list yet.",
    "131056": "WhatsApp is slowing this account down. Try again in a minute.",
    "130429": "WhatsApp is slowing this account down. Try again in a minute.",
    "132000": "The template and its values don't match. Check the message's variables.",
    "132001": "WhatsApp can't find this template. It may have been deleted.",
    "132005": "The template and its values don't match. Check the message's variables.",
    "132012": "The template and its values don't match. Check the message's variables.",
    "190": "Your WhatsApp connection has expired. Reconnect it in Settings.",
    # Reported by Meta after the send (delivery webhook), or by a later send attempt.
    "131047": "More than 24 hours since their last message, so WhatsApp needs an approved template",
    "131049": "Meta held it back so this person doesn't get too many marketing messages. Try again in a few days",
    "131048": "Too many messages were reported as spam; Meta slowed sending",
    "131050": "They turned off marketing messages from businesses",
    "131042": "A payment problem on your Meta account",
    # From upload._META_CODE_REASONS (broadcast failure buckets).
    "131058": "This template can only be sent from Meta's public test numbers.",
    "133010": "The sending number isn't registered on WhatsApp yet.",
    "200": "Your WhatsApp connection is missing a permission. Reconnect it in Settings.",
    "10": "Your WhatsApp connection is missing a permission. Reconnect it in Settings.",
    "100": "WhatsApp refused the message details. Check the template and its values.",
    "131031": "Your WhatsApp business account is locked by Meta. Check it in Meta Business Manager.",
    "131051": "WhatsApp can't send this kind of message.",
    "131052": "The customer's media couldn't be downloaded by WhatsApp.",
    "131053": "WhatsApp couldn't upload the media in this message.",
    "131021": "The sender and the customer number are the same.",
    "131000": "WhatsApp had a problem on its side. Try again later.",
    "131016": "WhatsApp is busy right now. Try again later.",
    "130472": "WhatsApp is running an experiment, so this person can't get the message.",
}

# The code each short slug stands for (so "undeliverable" and 131026 read the same).
_CODE_FOR_SLUG: dict[str, str] = {
    "test_template_only": "131058",
    "ecosystem_cap": "131049",
    "re_engagement_required": "131047",
    "recipient_not_allowed": "131030",
    "undeliverable": "131026",
    "number_not_registered": "133010",
    "token_invalid": "190",
    "permission_denied": "200",
    "bad_request": "100",
}

# Short reasons the sending code writes itself (auto_message_sends.reason, silence_nudge_jobs.skip_reason,
# reengagement_logs.reason ...), in plain words.
REASON_TEXT: dict[str, str] = {
    # auto_message_sends
    "no_rule": "No message is set up for this event yet",
    "ai_auto_reply_off": "Not sent: Instant templates were off in Settings > Auto-Reply",
    "duplicate": "Skipped: this person was already messaged recently",
    "opted_out": "They said stop, so nothing is sent to them",
    "template_not_approved": "The template isn't approved by Meta right now",
    "rule_removed_or_off": "The message was turned off before it was due",
    "quiet_hours": "Held back until the morning",
    "interrupted": "Interrupted before it went out",
    "not_on_whatsapp": "This number is not on WhatsApp",
    "blocked": "This person is blocked, so nothing is sent",
    # silence nudges (gate wording from automation_guards / silence_nudge)
    "opted out": "They said stop, so nothing is sent to them",
    "whatsapp undeliverable": "This number is not on WhatsApp",
    "no phone": "This person has no phone number",
    "lead blocked": "This person is blocked, so nothing is sent",
    "lead converted": "They already bought, so no nudge was sent",
    "ai disabled for lead": "The AI agent is switched off for this person",
    "escalated to human": "A person on your team is handling this chat",
    "open handover": "A person on your team is handling this chat",
    "active intake session": "They are in the middle of an order, so no nudge was sent",
    "daily cap reached": "Already sent the most nudges allowed for today",
    "lead replied": "They replied before it was due, so it wasn't needed",
    "lead missing": "The person was removed",
    "24h window closed": "More than 24 hours since their last message, so WhatsApp needs an approved template",
    "ai_reply quota exhausted": "Your AI reply limit for this month is used up",
    "unhandled error": "Something went wrong while sending it",
    "channel send returned no id": "WhatsApp didn't send it",
    # follow-up steps
    "skipped_window": "More than 24 hours since their last message and no approved template was set for this step",
    "outside_window": "More than 24 hours since their last message and no approved template was set for this step",
    "send_failed": "WhatsApp didn't send it",
}

_CODE_RE = re.compile(r'"code"\s*:\s*(\d+)')
_HASH_CODE_RE = re.compile(r"\(#(\d{2,6})\)")
_MESSAGE_RE = re.compile(r'"message"\s*:\s*"([^"]+)"')

_KIND_BY_CODE = {
    "131026": "undeliverable",
    "131047": "window",
    "131049": "retry", "131048": "retry", "131056": "retry", "130429": "retry", "131016": "retry",
    "131050": "stopped",
    "131030": "other",
    "132000": "template", "132001": "template", "132005": "template", "132012": "template",
    "131058": "template",
}
_KIND_BY_SLUG = {
    "opted_out": "stopped", "opted out": "stopped", "blocked": "stopped", "lead blocked": "stopped",
    "template_not_approved": "template",
    "24h window closed": "window", "skipped_window": "window", "outside_window": "window",
    "not_on_whatsapp": "undeliverable", "whatsapp undeliverable": "undeliverable",
    "quiet_hours": "retry",
    "lead replied": "none", "lead converted": "none", "daily cap reached": "none",
    "duplicate": "none", "no_rule": "none",
}


def meta_code(raw) -> str | None:
    """The numeric Meta code in a raw error (JSON or "(#131047)"), or an int/str code itself."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return str(raw)
    text = str(raw).strip()
    if not text:
        return None
    if text.isdigit() and text in META_CODE_TEXT:
        return text
    m = _CODE_RE.search(text) or _HASH_CODE_RE.search(text)
    return m.group(1) if m else None


def _looks_plain(text: str) -> bool:
    """Already a human sentence (written by our own code), not JSON / a slug / a stack dump."""
    return " " in text and "{" not in text and "Traceback" not in text and len(text) <= 300


def explain(raw, code=None) -> dict:
    """Plain words for a raw reason. Returns {text, kind, code}; never raises, never empty."""
    text = str(raw or "").strip()
    found = meta_code(code) or meta_code(text)
    if not found and text:
        slug_code = _CODE_FOR_SLUG.get(text)
        if slug_code:
            found = slug_code
    if found and found in META_CODE_TEXT:
        return {"text": META_CODE_TEXT[found], "kind": _KIND_BY_CODE.get(found, "other"), "code": found}
    key = text.lower()
    if key in REASON_TEXT:
        return {"text": REASON_TEXT[key], "kind": _KIND_BY_SLUG.get(key, "other"), "code": found}
    if text and _looks_plain(text) and not _CODE_RE.search(text):
        lowered = key
        kind = "other"
        if "opted out" in lowered or "said stop" in lowered or "blocked" in lowered:
            kind = "stopped"
        elif "24 hours" in lowered or "24h" in lowered:
            kind = "window"
        elif "template" in lowered and ("approved" in lowered or "paused" in lowered or "deleted" in lowered):
            kind = "template"
        return {"text": text, "kind": kind, "code": found}
    message = _MESSAGE_RE.search(text) if text else None
    if found:
        return {"text": f"{UNKNOWN} (code {found})", "kind": "other", "code": found}
    if message:
        return {"text": f"{UNKNOWN}: {message.group(1)[:150]}", "kind": "other", "code": None}
    return {"text": UNKNOWN, "kind": "other", "code": None}


def plain_reason(raw, code=None) -> str:
    return explain(raw, code)["text"]
