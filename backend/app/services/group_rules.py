"""Customers > Groups that fill themselves (customer_groups.kind = 'rule').

A rule is a saved set of the All people filters (routes/leads.py LeadFilters), so a
rule group always holds exactly the people that filtering All people by hand would show.
Nothing is copied: members are worked out from the rule every time the group is read or
used, so people join and leave by themselves. Dates are rolling ("added in the last 60
days"), never fixed, or the group would stop updating.

Stored shape (customer_groups.rule jsonb), every key optional but at least one set:
  segment        "A" | "B" | "C" | "D"           Status Hot / Warm / Cold / Not interested
  buyer          true                            Status Buyers
  source_filter  "inbound" | "organic" | "meta_ads" | "broadcast"
  broadcast_id   uuid  (only with source_filter "broadcast")
  ad_campaign_id uuid  (only with source_filter "meta_ads")
  added_days     1..365                          Added in the last N days
  assigned_to    caller id | "unassigned" | "ai_agent"
  reply_window   "open" | "closed"
  bought         "repeat" | "quiet"
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

IST = timezone(timedelta(hours=5, minutes=30))

# Keys copied straight onto LeadFilters. added_days is turned into date_from.
_FILTER_KEYS = ("segment", "buyer", "source_filter", "broadcast_id", "ad_campaign_id",
                "assigned_to", "reply_window", "bought")


class GroupRule(BaseModel):
    segment: str | None = Field(None, pattern="^[ABCD]$")
    buyer: bool | None = None
    source_filter: str | None = Field(None, pattern="^(inbound|organic|meta_ads|broadcast)$")
    broadcast_id: str | None = None
    ad_campaign_id: str | None = None
    added_days: int | None = Field(None, ge=1, le=365)
    assigned_to: str | None = Field(None, max_length=64)
    reply_window: str | None = Field(None, pattern="^(open|closed)$")
    bought: str | None = Field(None, pattern="^(repeat|quiet)$")

    @field_validator("broadcast_id", "ad_campaign_id")
    @classmethod
    def _uuid(cls, v):
        if v in (None, ""):
            return None
        return str(UUID(str(v)))

    @field_validator("buyer")
    @classmethod
    def _buyer_true_only(cls, v):
        # "Not a buyer" is not a Status choice on All people; keep the rule to what the screen offers.
        return True if v else None

    @model_validator(mode="after")
    def _consistent(self):
        if self.broadcast_id and self.source_filter != "broadcast":
            raise ValueError("A broadcast can only be picked with Came from: Broadcast")
        if self.ad_campaign_id and self.source_filter != "meta_ads":
            raise ValueError("A campaign can only be picked with Came from: Meta Ads")
        if self.segment and self.buyer:
            raise ValueError("Pick one Status")
        if not self.as_dict():
            raise ValueError("Add at least one rule")
        return self

    def as_dict(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v not in (None, "")}


def parse_rule(raw) -> dict | None:
    """A stored rule as a clean dict, or None when it is missing or no longer valid."""
    if not isinstance(raw, dict):
        return None
    try:
        return GroupRule(**raw).as_dict()
    except Exception:
        return None


def apply_rule(filters, rule: dict):
    """The page's filters narrowed by a group's rule (both must hold), or None when they
    contradict each other (e.g. the page says Warm and the group is Hot people), which
    means nobody matches. `filters` is a LeadFilters; a copy is returned."""
    updates: dict = {"group_id": None}
    for key in _FILTER_KEYS:
        wanted = rule.get(key)
        if wanted in (None, ""):
            continue
        current = getattr(filters, key)
        if current not in (None, "") and current != wanted:
            return None
        updates[key] = wanted
    days = rule.get("added_days")
    if days:
        since = (datetime.now(IST).date() - timedelta(days=int(days) - 1)).isoformat()
        current_from = filters.date_from
        updates["date_from"] = max(current_from, since) if current_from else since
    return filters.model_copy(update=updates)


def describe(rule: dict, names: dict | None = None) -> str:
    """One short line for the Groups table, e.g. "Hot · came from broadcast diwali_offer ·
    added in the last 60 days". `names` may hold the broadcast, campaign and caller names."""
    names = names or {}
    parts: list[str] = []
    seg = {"A": "Hot", "B": "Warm", "C": "Cold", "D": "Not interested"}.get(rule.get("segment") or "")
    if seg:
        parts.append(seg)
    if rule.get("buyer"):
        parts.append("Buyers")
    src = {"inbound": "came in by themselves", "organic": "came without an ad",
           "meta_ads": "came from Meta ads", "broadcast": "came from a broadcast"}.get(rule.get("source_filter") or "")
    if rule.get("broadcast_id") and names.get("broadcast"):
        src = f"came from broadcast {names['broadcast']}"
    elif rule.get("ad_campaign_id") and names.get("campaign"):
        src = f"came from ad campaign {names['campaign']}"
    if src:
        parts.append(src)
    if rule.get("bought") == "repeat":
        parts.append("bought 2+ times")
    elif rule.get("bought") == "quiet":
        parts.append("not back in 90 days")
    if rule.get("reply_window"):
        parts.append(f"reply window {rule['reply_window']}")
    if rule.get("assigned_to"):
        parts.append({"unassigned": "nobody handling", "ai_agent": "AI agent handling"}.get(
            rule["assigned_to"], f"handled by {names['caller']}" if names.get("caller") else "one team member"))
    if rule.get("added_days"):
        parts.append(f"added in the last {rule['added_days']} days")
    return " · ".join(parts)
