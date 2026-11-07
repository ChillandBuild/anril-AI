# Send SMS: two tabs, phone cards, preview popup (spec + plan)

Agreed with Prem on 2026-11-06/07 through a 9-question interview. Mockups were shown in chat.

## Spec

**Outcome.** Send SMS has two tabs at the top:
- **Saved templates**: "Pick a sender, then one of its approved templates."
- **DLT Manual**: "New sender, entity or message? Type the DLT details yourself."

Templates show as phone-style SMS cards. Pressing Send opens a popup with SMS credits first and the rupee cost second.

**User.** A client such as KELIR who sends fee reminders and alerts from senders already added in DLT Manager.

**Worked example (Saved templates).**
1. KELIR taps the chip "KELIR · 4".
2. They tap the #14893 card ("Dear {#var#}, your fee of Rs.{#var#} is due…").
3. They map Variable 1 to Name and Variable 2 to a contact column.
4. They pick 248 parents and choose Right now, then press Send SMS.
5. The popup shows:
   - the bubble filled with Prem's values;
   - 248 will get it, plus each skip reason with a count (Duplicate number 2, Not an Indian mobile number 3);
   - **496 SMS credits**, then credits left after, then **₹64.58 (₹0.1302 per SMS)**;
   - the button "Send to 248 people".

**Worked example (DLT Manual).**
1. KELIR picks sender KELIR. The list holds only added senders, with a "+ Add sender" link to DLT Setup → Sender ID. The Entity ID fills in from the sender and can be edited.
2. They paste Template ID 1707171234567890123 and the exact text.
3. Live checks run:
   - "Matches saved template #14894. Use it" switches to Saved templates with that card picked.
   - A curly quote (’) gets a warning with a "Fix quotes" button.
   - A leftover {#var#} gets an error.
   - The language label reads, for example: "Unicode (Tamil) · 70 characters per SMS · this message = 2 SMS".
4. After the send, the success notice offers **Save to my templates**. It opens the existing Add template form, prefilled. The button is hidden when the text matches a saved template.

**Rules.**
- The ₹ figure uses the same price as the "Your plan" card: Bulk9 wallet ₹ ÷ SMS left (verified on KELIR as ₹0.1302 = You Sell, 2026-11-07), shown to 4 decimals. If the wallet is unknown, the ₹ line is hidden.
- The client never sees the buying price. No money is stored on sends (the test_preview_counts_and_campaign_storage_have_no_money test stays green).
- Senders are never typed freely. The Bulk9 docs require the sender to be added in DLT Manager first.
- Unicode stays automatic, with no language list.
- One card design is shared by the Templates tab and Send: a teal "Variable N" pill, the sender avatar, and the bubble. The Templates tab gets the same sender chips. "Use this template" opens Send with that sender and card already picked.
- Kept: variable mapping, the link warning, Who gets it, When, and the night-hold notice (also shown in the popup).
- The "Name" field becomes "Name this send (optional)", auto-filled as "KELIR · 14893 · 7 Nov" or "KELIR · DLT Manual · 7 Nov". An empty name falls back to that default.
- The right panel slims to the phone preview, plus the status, error and Send button. Counts and money move to the popup.

**Out of scope.**
- Getting the category from Bulk9.
- Changing plan prices.
- Removing the word "campaign" from the dashboard and detail pages.
- Backend changes. The preview API already returns the counts and the skip reasons.

**Success.**
- A saved template can be sent without opening a dropdown.
- The popup's ₹ equals credits × the plan price.
- DLT Manual cannot use a sender that hasn't been added.
- Typecheck, lint and vitest pass.

## Plan

1. helpers.ts: add pure functions, with vitest tests:
   - sendersFrom
   - matchSavedTemplate
   - curly-quote detect and fix
   - languageLine
   - planRate
   - popupCost
   - skipCounts
   - sendNameFor
2. TemplateCard.tsx (new): SmsBubble, SenderChips and TemplateCard (full / pick). TemplateList.tsx uses them, with sender chips.
3. SendForm.tsx:
   - the tabs;
   - the Saved picker (chips, search, cards);
   - DLT Manual fields with the checks and + Add sender;
   - the slim aside;
   - the name field;
   - ?template= preselects the tab, sender and card.
4. SendConfirm.tsx (new): the popup, replacing ConfirmModal on this page.
5. DltForms.tsx: AddTemplatePanel takes an `initial` prefill. Send shows Save to my templates after a DLT Manual send.
6. Checks: tsc, next lint, vitest, then a code review of the diff. The UI was not checked live (house rule).
