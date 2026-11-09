# Getting Meta's approval for Instant form leads

Anril reads Instant form leads with two Meta permissions it doesn't have yet. This guide takes you from "not allowed" to "approved", click by click.

| Permission | Why Anril needs it | What Meta said without it (live test, 9 Nov 2026) |
|---|---|---|
| `leads_retrieval` | Read the answers a person typed into the form | — |
| `pages_manage_ads` | List the Page's forms | "(#200) Requires pages_manage_ads permission to manage the object" |

Anril already has `pages_manage_metadata`, which lets it subscribe the Page to new-lead notifications, and `pages_show_list` / `pages_read_engagement`.

**Meta app:** ANRIL AI, App ID `2225044871604460`
**Login setup Anril uses to connect a Page:** Facebook Login for Business configuration `2226622718102220`

The order matters. Meta wants a **screen recording of the feature working in Anril** before it approves. Until approval, the feature already works for people who have a role on the Meta app, like you. So: set up → test on your own Page → record → submit.

---

## Step 0 — Check these first (10 minutes)

Open <https://developers.facebook.com/apps/2225044871604460/> and check each item:

1. **Business Verification is done.** Left menu → **App settings** → **Basic** → scroll to **Business verification**. It must say *Verified*. If it doesn't, follow the link there. Meta asks for a company document and takes 1–5 working days.
2. **App is Live.** The top bar shows **App Mode: Live**.
3. **These fields are filled** on **App settings → Basic**:
   - **Privacy Policy URL**: must load and mention Facebook/Meta lead data.
   - **Terms of Service URL**.
   - **User data deletion**: a URL or instructions.
   - **App icon**: 1024×1024.
   - **Category**.
4. The new code is **deployed**: backend, database migration `248_meta_instant_forms.sql`, and frontend. Meta's reviewer and your recording both use the live site.

---

## Step 1 — Turn on lead notifications for the app (2 minutes)

Without this, Meta never tells Anril about a new lead, even when everything else is right.

1. App dashboard → left menu **Webhooks** (under *Products*). If it's missing: **Add product** → Webhooks → Set up.
2. In the dropdown at the top, choose **Page**.
3. You'll see the Page callback URL Anril already uses for Messenger. Keep it.
4. Scroll the field list to **leadgen** → click **Subscribe**.
5. Optional: click **Test** next to leadgen. Meta sends a sample. It has fake ids, so Anril logs that it couldn't read the lead. That's expected.

---

## Step 2 — Add the two permissions to Anril's Page login (3 minutes)

1. App dashboard → left menu **Facebook Login for Business** → **Configurations**.
2. Open the configuration with ID **2226622718102220**. This is the one the *Connect Facebook Page* button uses.
3. Click **Edit** and go to the **Permissions** step.
4. Tick **leads_retrieval** and **pages_manage_ads**. Leave everything already ticked as it is.
5. **Save**. The configuration ID stays the same, so no code change is needed.

---

## Step 3 — Test it on your own Page (15 minutes)

This works before approval because you're an admin of the ANRIL AI app.

**3a. Reconnect your Page so the new permissions land on its token**
1. Log in to Anril as the Bloom Matrix owner.
2. **Settings → Connect Channels → Facebook** → **Reconnect**, or Disconnect then Connect.
3. In Meta's window, pick your Page and **leave every permission switched on**, including *leads*.

**3b. Make sure the Page has a form**
1. Open <https://business.facebook.com/> → **All tools** → **Instant Forms**, with your Page selected.
2. If there's none: **Create form** → type *More volume* → add the questions **Full name**, **Phone number** and **Email**, plus one custom question such as *Which city?* → privacy policy link → **Publish**.

**3c. Turn it on in Anril**
1. Anril → **Meta Ads → Instant forms** → **Turn on**.
2. You should see "Found N form(s)" and your form listed.
3. Open the form → **WhatsApp message** → pick an approved template → set {{1}} = *First name* → **Save**.

**3d. Send a test lead**
1. Open Meta's **Lead Ads Testing Tool**: <https://developers.facebook.com/tools/lead-ads-testing>
2. **Page** = your Page, **Form** = the form from 3b.
3. If an old test lead exists, click **Delete lead** first. Meta allows one test lead per person per form.
4. Click **Create lead**. In the questions Meta asks, use **your own WhatsApp number**.
5. Within a few seconds:
   - ✅ The lead appears in Anril under the form, with every answer.
   - ✅ The template arrives on your WhatsApp.
   - ✅ The lead shows in **Inbound Leads** tagged *Instant form*.
6. The testing tool's **Track status** button shows Meta's side. *Success* with app **ANRIL AI** means the notification was delivered.

**If nothing shows up:**
- Instant forms says *Allow Anril to read your form leads*: Step 2 wasn't saved, or you didn't reconnect (3a).
- The testing tool says the delivery *failed*: Step 1 (leadgen not subscribed) or the callback URL.
- The lead shows but no WhatsApp arrived: the form has no template chosen, or the template has an image header (not supported yet). The red *Failed* badge's tooltip gives the reason.

---

## Step 4 — Record the screencast (10 minutes)

Record the screen at 1080p with no sound needed. Meta reviewers like captions, so add short on-screen text if your recorder can. Keep it to **2–3 minutes**. Shot list:

1. Anril login page → log in (shows a real product).
2. **Settings → Connect Channels → Connect Facebook Page.** Meta's window opens → pick the Page → show the permission list including *leads* and *ads on Pages* → Continue.
3. **Meta Ads → Instant forms** → **Turn on** → the forms list appears. *(This shows pages_manage_ads: listing the Page's forms.)*
4. Open a form → choose the WhatsApp template → Save.
5. Switch to the **Lead Ads Testing Tool** → Create lead.
6. Back in Anril → refresh the form → the new lead appears with its answers. *(This shows leads_retrieval.)*
7. Show the WhatsApp message arriving on the phone, either by holding the phone up or with a phone screen recording.
8. Open the lead in **Inbound Leads** to show it's handled like any other lead.

Save it as an MP4 under 100 MB.

---

## Step 5 — Submit for review (15 minutes)

1. App dashboard → **App Review** → **Permissions and Features**.
2. Search **leads_retrieval** → **Request advanced access**. Do the same for **pages_manage_ads**. Both go into the same submission.
   - If Meta marks another permission as *required* for these (for example `ads_management`), add it to the same submission.
3. Fill each request. The text below is ready to paste; replace CAPS words.

**leads_retrieval: "How will your app use this permission?"**
> Anril is a WhatsApp CRM for small businesses in India. Businesses connect their Facebook Page to Anril and run lead ads with Instant Forms. When a person submits a form, Meta notifies Anril through the leadgen webhook; Anril then uses leads_retrieval to read that single lead's answers (name, phone, email and the business's own questions) with the Page access token the business granted. Anril stores the answers in the business's own account, shows them in its dashboard under Meta Ads > Instant forms, adds the person to the business's lead list, and sends the WhatsApp template the business chose so the person gets a reply within seconds. Lead data is only visible to that business's own team and is never shared with other businesses or third parties.

**pages_manage_ads: "How will your app use this permission?"**
> Anril uses pages_manage_ads only to read the list of Instant Forms on the business's connected Page (GET /{page-id}/leadgen_forms): form name, status and questions. The business sees these forms in Anril, picks which WhatsApp template each form should send, and maps template blanks to form questions. Anril does not create, edit or delete forms or ads.

**Testing instructions for the reviewer** (in the same form):
> 1. Go to https://YOUR-ANRIL-DOMAIN/login and sign in with REVIEWER-EMAIL / REVIEWER-PASSWORD.
> 2. Open Meta Ads > Instant forms. The test Page "YOUR-PAGE-NAME" is already connected and its forms are listed.
> 3. Click the form "YOUR-FORM-NAME" to see each lead's answers, the ad it came from, and the WhatsApp message status.
> 4. To see a new lead arrive: use the Lead Ads Testing Tool on Page "YOUR-PAGE-NAME", form "YOUR-FORM-NAME", then refresh the form in Anril.
> The screencast shows the full flow from connecting the Page to the WhatsApp reply.

4. Create the reviewer login first: an Anril **team member** on the Bloom Matrix account with Meta Ads view access. Don't share the owner login.
5. Upload the screencast on each permission → tick the data-use agreements → **Submit for review**.

**How long:** usually 2–7 working days. Meta emails you, and the result shows on the App Review page.

**If it's rejected:** Meta says which point failed, usually "the screencast doesn't show the permission being used". Re-record that part and resubmit. Nothing is lost.

---

## Step 6 — After approval: switch on each customer (2 minutes each)

The approval covers every Anril customer, but each customer's Page token was made before the permissions existed. For each customer:

1. **Settings → Connect Channels → Facebook → Reconnect**, done by a Page admin, keeping every permission switched on.
2. **Meta Ads → Instant forms → Turn on.**
3. Open each form → choose its WhatsApp template.
4. **Only if their leads still don't arrive:** the Page may restrict which apps can read leads. The Page admin opens <https://business.facebook.com/settings> → **Integrations** → **Leads access** → pick the Page → **CRMs** tab → **Assign CRM** → **ANRIL AI**.

Anril also checks every 30 minutes for leads whose notification never arrived, and sends the template to any that are under a day old.
