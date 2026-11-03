# SMS UI cleanup (2026-11-04)

Decisions from the screenshot review. One commit per task; push only when Prem says so.

## Tasks

- [x] **1. Wallet only on the Dashboard.** Remove the wallet bar + Add credit button + credit popup from SmsShell.
  Dashboard WalletCard gets the Add credit form inline (amount, note, Request credit) and the "₹X requested on
  3 Nov · waiting" line. Transactions loses its "Balance" card (keeps Balance history). Setup checklist on the
  Dashboard collapses to one line ("Setup · 1 of 5 done · next: …  Show steps"). Before the Bulk9 key is set:
  Dashboard = collapsed checklist + Add credit; DLT Setup = PE-TM; other pages = one short "Setup in progress" card.
  *Accept:* no wallet/Add credit on any page but the Dashboard; credit request works inline; tests for the
  amount check and the setup summary.
- [x] **2. Repeated titles off.** Remove card headers #1, #2 (SendForm "Send SMS"), #16 "Contacts", #17 "Groups";
  drop hints that repeat the app header.
- [x] **3. PE-TM: "I've sent the binding request" button** in place of the screenshot upload. Backend route rings the
  operator bell (dedup per entity per hour, like today). Remove the upload card.
- [x] **4. Add Entity without proof files.** Remove the file field; send without screenshot_links; show Bulk9's message
  if it refuses.
- [x] **5. Send SMS layout A** (split composer: form left, preview + cost + Send right). Fits 1366×768 with no page
  scroll; numbers box ~4 lines and scrolls inside; preview one line. Phones stack and scroll.
- [ ] **6. Popups → inline** in ContactsTab, GroupsPanel, ContactModals, DltForms. Delete confirmations stay modals.
