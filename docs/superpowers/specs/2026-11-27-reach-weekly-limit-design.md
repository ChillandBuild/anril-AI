# Reach: weekly broadcast limit per person, set by each client — design

Date: 2026-11-27. Status: approved in chat (short design, medium change).

## Why
Today every client has the same hard-coded rule: a person gets at most 2 Reach campaigns per IST
calendar month, and anyone over it is silently skipped. Clients send at different rates (one wants 5 a
week, another 10), and on the Confirm step they want to see who is over the limit and choose, person by
person, who still gets this campaign — instead of losing all of them.

## What changes
1. **Week, not month.** The limit counts Reach campaigns a person got from **Sunday 00:00 IST to Saturday
   23:59 IST** (the current week). It replaces the monthly rule everywhere it applies: the Confirm-step
   preview, Send now, scheduled and drip runs.
2. **Each client sets the number.** Settings › Limits & Meta charges gets a card "Broadcasts per person per
   week (Sunday to Saturday)": a whole number **1–50**, default **2** for clients who never set it, applied
   only on **Save**. Read needs `settings.view`, Save needs `settings.manage`.
3. **Confirm step: a pick-list, styled like the opted-out box.** When people in the audience (uploaded
   list, group, or both) already reached the limit, an orange box says
   "N people already got L broadcasts this week (Sun D Mon – Sat D Mon). They'll be skipped unless you
   pick them." with a "Show N people" dropdown. Inside: "Select all · X of N picked", a search box, and one
   row per person — tick, name (when a lead exists), number, "K this week". **Nobody is ticked by default.**
   The "will get it" count and the Meta charge line include the picked people as you tick.
4. **Picks are honoured at send time.** A picked person is sent even though they are over the limit — on
   Send now, scheduled and drip runs. Anyone over the limit who was not picked (including someone who crosses
   it between Confirm and the send) is skipped as today.
5. **History.** New skips are labelled "skipped: weekly limit". Campaigns already skipped under the monthly
   rule keep "skipped: monthly limit".

## Unchanged
- Only Reach campaign sends count (`broadcast_recipients.send_status='sent'`); bills, order updates,
  reminders, Auto-Messages, replies and OTP never count.
- The bucket order in the preview (no opt-in → said stop → said no → blocked → over limit → will get it):
  the list only ever holds people who would otherwise get the campaign.
- The opted-out box and its tick, the blocked rule, the push-back stop.
- Meta's own marketing cap still applies on top (error 131049); a high client number can't get past it.

## Approaches considered
- **Chosen:** same counting as today with the window start moved from the 1st to Sunday; the client's number
  in one `app_settings` row (`reach_weekly_limit`) with its own small GET/PUT endpoint; picks sent as a list
  of phones and stamped onto each person in the campaign, so scheduled/drip runs already carry them in
  `scheduled_broadcasts.leads_json`. **No database migration.**
- Rejected: a new column on `scheduled_broadcasts` for the picks — not needed, `leads_json` already stores
  each person. Rejected: saving the number through the shared `PATCH /settings/` — that path once wiped a
  saved key by mistake (subsystem-notes, TeleCMI incident); a dedicated endpoint touches one key only.
- Rejected: a pop-up window for the list — the user asked for a dropdown in the box.

## Builder's calls (not the user's)
- Range 1–50 and no "limit off" switch (picking people on Confirm covers one-off exceptions).
- Old `monthly_limit` rows keep their label; the new skip reason is `weekly_limit`.
- If the limit or the count can't be read, the send fails open (as today) and uses the default 2.
