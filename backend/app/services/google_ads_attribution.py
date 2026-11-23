"""Parse Google Ads attribution tags out of the first inbound WhatsApp message.

Google Ads cannot inject Meta's `referral` object into a WhatsApp thread the way
Click-to-WhatsApp ads do. Instead we carry attribution in the click-to-chat
pre-filled message text: a client points a Google ad at a wa.me link whose
`?text=` payload ends with a bracket tag, e.g.

    https://wa.me/9198XXXXXXXX?text=Hi%2C%20I'm%20interested%20%5BGADS:summer_sale%5D

When the user taps send, that tag arrives as the first inbound message body and we
attribute the lead to a Google campaign. The link generator no longer writes a
[GCLID:...] tag (Google's {gclid} macro gets URL-encoded inside a wa.me link, so it never
carried a real click id, and nothing reads it without the Google API). The parser still
reads one if an old link carries it.

This module is pure text parsing — no DB, no network — so it is cheap to unit test.
"""
import re
from dataclasses import dataclass
from urllib.parse import quote

# [GADS:slug] / [GOOGLE:slug] / [GADS-slug] / [GADS_slug] — separator is one of : _ -
# Slug itself is letters, digits and underscores (no hyphen, to keep the separator
# unambiguous). Case-insensitive so clients can't fat-finger the casing.
_CAMPAIGN_RE = re.compile(r"\[(?:GADS|GOOGLE)[:_-]([A-Za-z0-9_]+)\]", re.IGNORECASE)
_GCLID_RE = re.compile(r"\[GCLID[:_-]([A-Za-z0-9_-]+)\]", re.IGNORECASE)


@dataclass(frozen=True)
class GoogleAdRef:
    """Attribution parsed from a pre-filled WhatsApp message."""
    campaign: str
    gclid: str | None = None

    @property
    def external_campaign_id(self) -> str:
        """Namespaced id stored on ad_campaigns.external_campaign_id.

        Prefixed with ``google:`` so it can never collide with a Meta ad id.
        """
        return f"google:{self.campaign}"


def parse_google_ref(text: str | None) -> GoogleAdRef | None:
    """Extract a Google Ads attribution tag from message text.

    Returns a GoogleAdRef when a [GADS:...] / [GOOGLE:...] tag is present, else
    None. A [GCLID:...] tag is captured opportunistically but is not required.
    """
    if not text:
        return None

    campaign_match = _CAMPAIGN_RE.search(text)
    if not campaign_match:
        return None

    gclid_match = _GCLID_RE.search(text)
    return GoogleAdRef(
        campaign=campaign_match.group(1),
        gclid=gclid_match.group(1) if gclid_match else None,
    )


# Slug rules must match what the parser accepts: letters, digits, underscores.
_SLUG_RE = re.compile(r"^[A-Za-z0-9_]+$")
_NON_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")
_DEFAULT_GREETING = "Hi, I'm interested"


def slugify_campaign(name: str | None) -> str:
    """Normalize a human campaign name into a parser-safe slug.

    "Summer Sale 2026!" -> "summer_sale_2026". Returns "" when nothing usable
    remains, so callers can reject empty input with a clear error.
    """
    collapsed = _NON_SLUG_RE.sub("_", (name or "").strip())
    return collapsed.strip("_").lower()


def build_tracked_wa_link(
    phone: str,
    campaign: str,
    *,
    gclid: str | None = None,  # ignored: kept so older callers still work; never written into the link
    greeting: str = _DEFAULT_GREETING,
) -> str:
    """Build a wa.me click-to-chat link whose pre-filled text carries the tag.

    Point a Google ad at the returned URL. When the user taps send, the [GADS:...]
    tag lands in the first inbound message and parse_google_ref() attributes it.

    Raises ValueError on an invalid campaign slug so a bad link can never ship —
    the parser would silently ignore a malformed tag, which is the exact
    "client messed up the link" failure this generator exists to prevent.
    """
    if not _SLUG_RE.match(campaign):
        raise ValueError(
            f"campaign slug must be letters, digits or underscores only: {campaign!r}"
        )

    number = phone.lstrip("+").replace(" ", "")
    text = f"{greeting} [GADS:{campaign}]"
    return f"https://wa.me/{number}?text={quote(text)}"
