import type { FaqEntry } from "./schema";

// Blog articles. Facts about Anril AI come from the SEO brief and the product; the rest is general guidance
// that does not depend on a number or a competitor. The WhatsApp API pricing article quotes no rupee rates: Meta's
// rate card is the source. We do not publish comparisons that name other companies.

export type Block = { type: "h2"; text: string } | { type: "p"; text: string } | { type: "ul"; items: readonly string[] };

export type Post = {
  slug: string;
  title: string;
  /** Shorter title for search results and the browser tab (under 60 characters with the site name). The H1 uses `title`. */
  seoTitle?: string;
  /** Under 155 characters. */
  description: string;
  published: string; // ISO date
  updated: string; // ISO date
  author: string;
  /** The one product page this article links to at the end. */
  link: { href: string; label: string };
  body: readonly Block[];
  faqs: readonly FaqEntry[];
  /** A draft is not published: no page, no listing, no sitemap entry. Remove the flag once every fact is verified. */
  draft?: boolean;
};

export const BLOG_AUTHOR = "Anril AI team";

const ALL_POSTS: readonly Post[] = [
  {
    slug: "how-to-choose-a-whatsapp-business-tool",
    seoTitle: "How to Choose a WhatsApp Business Tool",
    title: "How to choose a WhatsApp business tool: 7 questions to ask",
    description:
      "Choosing a WhatsApp tool for your business? Seven questions to ask about price, AI replies, languages, lead scoring, calls, payments and handover.",
    published: "2026-11-05",
    updated: "2026-11-05",
    author: BLOG_AUTHOR,
    link: { href: "/pricing", label: "Anril plans from ₹999 a month" },
    body: [
      { type: "p", text: "To choose a WhatsApp business tool, decide what you need it to do beyond sending messages, then ask each provider the same seven questions and compare the total monthly cost for your team. A tool that looks cheap on its price page can cost more once users, add-ons and message charges are included." },
      { type: "h2", text: "1. What is the total monthly cost?" },
      { type: "p", text: "Ask for the plan price, the cost of extra users, any add-ons you would need, and how billing works: monthly, quarterly or yearly, with or without taxes. On every provider, Meta also charges for the WhatsApp messages you send, and that is billed separately from the plan. Anril plans start from ₹999 a month (plus GST), or ₹799 a month on a yearly plan." },
      { type: "h2", text: "2. Does it use the official WhatsApp Business API?" },
      { type: "p", text: "The official API is what keeps your number safe when you send campaigns. Ask the provider how it connects to WhatsApp. Anril connects through Meta's official WhatsApp Business API." },
      { type: "h2", text: "3. How good are the AI replies, and how are they counted?" },
      { type: "p", text: "Ask to see the AI answer questions about your own business, not a canned demo. Ask how replies are counted and what happens when you reach the limit. With Anril, only AI replies are counted, not customer messages." },
      { type: "h2", text: "4. Does it reply in your customers' language?" },
      { type: "p", text: "Many customers in Tamil Nadu write Tamil in English letters. Anril replies in Tanglish by default and can reply in any language. It also understands voice notes." },
      { type: "h2", text: "5. Does it tell you who is ready to buy?" },
      { type: "p", text: "A long list of chats is not much help. Look for lead scoring and a clean handover to a person with the whole conversation. Anril scores each lead Hot, Warm or Cold and updates the score with every message." },
      { type: "h2", text: "6. Can it handle calls and payments too?" },
      { type: "p", text: "If your team also makes sales calls, or you take payments in chat, check whether the same tool covers them. Anril CallIQ records and scores calls and understands Tamil calls, and Anril Commerce sends Razorpay payment links and tracks orders." },
      { type: "h2", text: "7. Can you try it on your own enquiries first?" },
      { type: "p", text: "Ask for a demo with questions your customers really ask. Anril does not offer a free trial, but demos are free and unlimited, online or at our Coimbatore office." },
    ],
    faqs: [
      { q: "Do I pay Meta separately on top of the plan?", a: "Yes, on every provider. Meta charges for delivered business messages, and the provider's plan is billed separately, so ask exactly what the plan includes." },
      { q: "How much does Anril cost?", a: "Plans start from ₹999 a month (plus GST), or ₹799 a month on a yearly plan. WhatsApp message charges from Meta are separate." },
      { q: "Is there a free trial?", a: "There is no free trial, but demos are free and unlimited, online or at our Coimbatore office." },
    ],
  },
  {
    slug: "what-is-a-lead-management-system",
    seoTitle: "What Is a Lead Management System?",
    title: "What is a lead management system, and how do you choose one?",
    description:
      "A lead management system collects every enquiry, scores it and tells your team who to call first. Learn what it does and what to check before you choose one.",
    published: "2026-11-04",
    updated: "2026-11-04",
    author: BLOG_AUTHOR,
    link: { href: "/whatsapp-crm", label: "Anril's WhatsApp CRM and lead management" },
    body: [
      { type: "p", text: "A lead management system collects every enquiry your business gets, keeps it in one list, scores how ready each person is to buy, and tells your team who to follow up first. It replaces scattered phone chats and spreadsheets with a single place where no enquiry is forgotten." },
      { type: "h2", text: "What a lead management system does" },
      { type: "ul", items: [
        "Captures leads from every source, such as WhatsApp, Instagram, Facebook, calls and forms.",
        "Keeps each person's conversation history with their record.",
        "Scores leads, for example Hot, Warm or Cold.",
        "Assigns leads to the right team member.",
        "Reminds the team to follow up, or follows up automatically.",
        "Reports what is working: where leads come from and how they move."
      ] },
      { type: "h2", text: "Signs you need one" },
      { type: "ul", items: [
        "Enquiries arrive on several channels and nobody sees them all.",
        "Replies are slow, or some messages are never answered.",
        "Your team does not know which leads to call first.",
        "Lead details live in personal phones or spreadsheets.",
        "When someone leaves, their leads leave with them."
      ] },
      { type: "h2", text: "What to check before you choose" },
      { type: "ul", items: [
        "Channels: does it bring in the channels your customers use? Anril covers WhatsApp, Instagram and Facebook.",
        "Speed: can it answer instantly, for example with an AI chatbot, so leads do not wait?",
        "Scoring: does it tell you who is ready to buy, and can you describe what a buying step is in your business?",
        "Handover: does the chat pass to a person with the whole conversation?",
        "Team: how many users are included, and can managers see reports?",
        "Cost: the plan plus any message charges. Anril plans start from ₹999 a month (plus GST), with WhatsApp message charges from Meta separate."
      ] },
      { type: "h2", text: "Lead management and a CRM" },
      { type: "p", text: "The two overlap. A lead management system focuses on the early stage: capturing, scoring and following up enquiries. A CRM usually covers the whole customer relationship afterwards. In Anril, leads, conversations, payments and orders are kept together, so you do not need a separate tool for each stage." },
    ],
    faqs: [
      { q: "Is a lead management system the same as a CRM?", a: "They overlap. Lead management focuses on capturing, scoring and following up enquiries, while a CRM covers the wider customer relationship. In Anril, leads, conversations, payments and orders are kept together." },
      { q: "How does Anril score leads?", a: "Anril scores each lead Hot, Warm or Cold from what they asked and how they answered, and updates the score with every new message." },
      { q: "How much does it cost?", a: "Anril plans start from ₹999 a month (plus GST)." },
    ],
  },
  {
    slug: "case-study-customer-business-ai-replies",
    seoTitle: "Case study: Anril in a Customer-Facing Business",
    title: "Case study: how a customer-facing business in our own group uses Anril",
    description:
      "A customer-facing business in our own group has used Anril for 6 to 7 months for AI replies and bulk messaging. What changed, and what we have not measured.",
    published: "2026-11-04",
    updated: "2026-11-05",
    author: BLOG_AUTHOR,
    link: { href: "/whatsapp-chatbot", label: "Anril's WhatsApp AI chatbot" },
    body: [
      { type: "p", text: "A customer-facing business in our own group has used Anril for the last 6 to 7 months. Its team reports that enquiries are no longer left seen but unanswered: each query gets a reply at the moment it arrives. This page is one business's story, not a promise of results, and it is clear about what we have not measured." },
      { type: "h2", text: "Who this is" },
      { type: "p", text: "This is not an outside customer. It is a business in the same group that builds Anril, and we say so because you should know. We are not naming the business." },
      { type: "h2", text: "What the business uses Anril for" },
      { type: "ul", items: ["AI replies to customer enquiries, answered from the information the business has given Anril.", "Bulk message sending to reach its customers."] },
      { type: "p", text: "It does not use Anril's telecalling and call scoring in a real situation yet, so this case study says nothing about CallIQ." },
      { type: "h2", text: "What changed for the team" },
      { type: "ul", items: ["Faster replies: customers get an answer straight away.", "No enquiry left seen but unanswered: every query is answered at the moment it comes in."] },
      { type: "h2", text: "What we have not measured" },
      { type: "p", text: "We have not published a before-and-after reply time, a change in sales or a cost saving, because we have not measured them in a way we could prove. Conversation volumes vary from month to month, and another business will see different numbers. When we have measured figures, we will add them here with the date." },
      { type: "h2", text: "What this means for your business" },
      { type: "p", text: "If your customers message you more often than your team can answer, the same setup can apply: Anril replies in seconds from your own business information, in Tanglish or any language, and hands the chat to your team when a person is needed. Book a free demo and we will set it up with questions like your customers really ask." },
    ],
    faqs: [
      { q: "Is this an outside customer?", a: "No. It is a customer-facing business in the same group that builds Anril. We do not name it." },
      { q: "Will my business get the same results?", a: "Not necessarily. This is one business's experience over 6 to 7 months, and results depend on your business and your enquiries." },
      { q: "Does the business use Anril for telecalling?", a: "Not yet in a real situation, so this case study does not cover call recording or call scoring." },
    ],
  },
  {
    slug: "send-bulk-whatsapp-messages-without-getting-blocked",
    seoTitle: "Bulk WhatsApp Messages Without Getting Blocked",
    title: "How to send bulk WhatsApp messages without getting your number blocked",
    description:
      "Use the official WhatsApp Business API, approved templates and opted-in contacts. Here is how bulk WhatsApp messaging works without risking your number.",
    published: "2026-11-02",
    updated: "2026-11-02",
    author: BLOG_AUTHOR,
    link: { href: "/bulk-whatsapp-sender", label: "Anril Reach: bulk WhatsApp campaigns the official way" },
    body: [
      { type: "p", text: "Short answer: send bulk WhatsApp messages through the official WhatsApp Business API, use Meta-approved templates, message only people who agreed to hear from you, and make it easy to stop. Numbers get blocked when businesses blast unapproved messages to people who never asked for them." },
      { type: "h2", text: "Why numbers get blocked" },
      { type: "p", text: "WhatsApp is built for conversations between people who know each other. When many recipients report or block a sender, or when a sender uses unofficial tools to push messages out in bulk, WhatsApp restricts the number. The usual causes are:" },
      { type: "ul", items: ["Messaging people who never gave you their number or never agreed to hear from you.", "Sending the same promotional message to a very large list in one go.", "Using unofficial bulk-sender apps that send from an ordinary WhatsApp or WhatsApp Business app number.", "Giving recipients no easy way to opt out."] },
      { type: "h2", text: "Use the official WhatsApp Business API" },
      { type: "p", text: "The WhatsApp Business API is Meta's official route for businesses that want to message many customers. Messages go out through an approved provider instead of from a phone, and Meta's rules for templates and quality apply. Anril Reach sends campaigns this way, so you do not have to rely on a workaround that can put your number at risk." },
      { type: "h2", text: "Use approved templates for business-started messages" },
      { type: "p", text: "A template is a message whose wording Meta has reviewed in advance, such as an offer, an event reminder or an update. When your business starts the conversation, the message goes out as an approved template. Keep templates clear and specific, say who you are, and avoid misleading wording, since a template that confuses people gets reported." },
      { type: "h2", text: "Message only people who agreed" },
      { type: "p", text: "Collect permission before you send marketing messages: a form on your website, a tick box at billing, or a customer who messaged you first. A list of people who expect to hear from you gets read and answered. A list bought from someone else gets blocked." },
      { type: "h2", text: "Segment your list and schedule sensibly" },
      { type: "p", text: "Do not send everyone the same message. Split contacts into groups, for example by what they bought or enquired about, and send each group something relevant. Schedule campaigns for hours when people are likely to read them, not in the middle of the night. Anril lets you build segments and schedule campaigns, then shows delivery and engagement reports so you can see who received, read and replied." },
      { type: "h2", text: "Be ready for replies" },
      { type: "p", text: "A campaign that gets replies but no answers wastes the effort and annoys people. With Anril, the AI chatbot replies to customers instantly and scores the lead Hot, Warm or Cold, so your team can start with the people most likely to buy." },
      { type: "h2", text: "A simple checklist" },
      { type: "ul", items: ["Send through the official WhatsApp Business API.", "Use approved templates written in plain, honest wording.", "Message only contacts who agreed to hear from you.", "Segment the list and send relevant messages.", "Make opting out easy and respect it.", "Reply to responses quickly."] },
    ],
    faqs: [
      { q: "Can I send bulk WhatsApp messages from my normal WhatsApp Business app?", a: "The app is built for one-to-one chats, and using unofficial tools to send in bulk from it can get a number restricted. For campaigns, use the WhatsApp Business API through a provider such as Anril." },
      { q: "Does WhatsApp charge for business messages?", a: "Yes. Meta charges for business messages separately from your Anril plan." },
      { q: "Can I keep my existing number?", a: "Yes, your number can be connected to Anril. If you do not need bulk campaigns, you can keep using the WhatsApp Business app instead." },
    ],
  },
  {
    slug: "what-is-a-whatsapp-chatbot",
    seoTitle: "What Is a WhatsApp Chatbot? Do You Need One?",
    title: "What is a WhatsApp chatbot, and does a small business need one?",
    description:
      "A WhatsApp chatbot replies to customer messages automatically. Here is what it can do, when a small business needs one, and what to look for before you buy.",
    published: "2026-11-02",
    updated: "2026-11-02",
    author: BLOG_AUTHOR,
    link: { href: "/whatsapp-chatbot", label: "Anril's WhatsApp AI chatbot" },
    body: [
      { type: "p", text: "A WhatsApp chatbot is software that replies to customer messages on WhatsApp automatically. A good one answers common questions at once, collects what you need to know about the customer, and passes the chat to a person when the customer needs one. A small business needs one when customers message more often than the team can answer, or when messages arrive outside working hours." },
      { type: "h2", text: "Rule-based bots and AI chatbots" },
      { type: "p", text: "Older chatbots follow a fixed menu: press 1 for timings, press 2 for prices. They work for simple needs but fail as soon as a customer types something the menu did not expect. An AI chatbot reads the customer's actual message and answers from information you give it about your business, so it can handle questions asked in different ways." },
      { type: "h2", text: "What a WhatsApp chatbot can do" },
      { type: "ul", items: ["Reply in seconds, including at night and on holidays.", "Answer questions about your services, prices, timings and location.", "Send photos and price lists.", "Reply in the customer's language. Anril replies in Tanglish by default and can use any language.", "Understand voice notes.", "Score each lead Hot, Warm or Cold, and hand hot leads to your team."] },
      { type: "h2", text: "Does a small business need one?" },
      { type: "p", text: "Ask three questions. Do customers message you outside working hours? Do the same questions arrive again and again? Do some enquiries go cold because nobody replied quickly? If the answer to any of them is yes, a chatbot will probably save time and recover enquiries you are losing today. If you get a handful of messages a week and answer all of them within minutes, you may not need one yet." },
      { type: "h2", text: "What to check before you buy" },
      { type: "ul", items: ["Can it answer from your own information, and can you edit that information yourself?", "Does it reply in the languages your customers use?", "Can a person take over the chat, with the conversation so far?", "Does it tell you which leads are ready to buy?", "How is it priced? With Anril, only AI replies are counted, not customer messages."] },
      { type: "h2", text: "The human handover matters" },
      { type: "p", text: "No chatbot should try to handle everything. The best setup answers the routine questions and gives your team the conversations that need a person, together with everything said so far. That keeps customers from repeating themselves and keeps your team's time for the people who are ready to buy." },
    ],
    faqs: [
      { q: "Will customers know they are talking to an AI?", a: "If a customer asks, Anril's chatbot says it is an AI assistant." },
      { q: "Can a chatbot reply in Tamil?", a: "Anril replies in Tanglish by default and can reply in any language. It also understands voice notes." },
      { q: "How much does a WhatsApp chatbot cost?", a: "Anril plans start from ₹999 a month (plus GST). WhatsApp message charges from Meta are separate." },
    ],
  },
  {
    slug: "how-to-track-telecaller-performance",
    seoTitle: "How to Track Telecaller Performance (Scorecard)",
    title: "How to track telecaller performance (with a simple scorecard)",
    description:
      "Track telecaller performance with a few clear measures: call volume, talk time, follow-ups and call quality. Includes a simple scorecard you can use today.",
    published: "2026-11-02",
    updated: "2026-11-02",
    author: BLOG_AUTHOR,
    link: { href: "/telecaller-software", label: "Anril CallIQ: call recording and Tamil call analysis" },
    body: [
      { type: "p", text: "To track telecaller performance, measure four things for each person every week: how many calls they make, how long they talk, whether they follow up, and how good the calls are. The first three are easy to count. The fourth, call quality, is the one most teams skip, and it is the one that explains why two people with the same number of calls close very different numbers of sales." },
      { type: "h2", text: "Start with activity" },
      { type: "ul", items: ["Calls made per day.", "Talk time: how long the calls actually last.", "Calls answered versus not answered.", "Leads called within a target time of arriving."] },
      { type: "p", text: "These numbers show effort. On their own they can mislead, because a telecaller can make many short, poor calls." },
      { type: "h2", text: "Add follow-up discipline" },
      { type: "p", text: "Most sales are lost between the first call and the decision. Count how many leads each telecaller followed up as promised, and how many were left untouched. A lead who said \"call me on Friday\" and heard nothing is a lost sale." },
      { type: "h2", text: "Score the quality of the call" },
      { type: "p", text: "Quality is what the customer hears: a clear opening, good questions, honest answers to objections and a clear next step. Many teams review a few recordings by hand. That is slow, and it covers only a few calls. Anril CallIQ records every call, understands Tamil conversations and scores them, so owners and managers can see in one place who is closing and who needs help." },
      { type: "h2", text: "A simple weekly scorecard" },
      { type: "p", text: "Give each telecaller a score out of 5 on each line, and discuss the lowest line in a short weekly one-to-one:" },
      { type: "ul", items: ["Speed: how quickly new leads are called.", "Volume: calls and talk time against the target.", "Follow-up: promised callbacks done on time.", "Call quality: opening, questions, objection handling, next step.", "Outcome: leads moved forward or closed."] },
      { type: "h2", text: "Make sure they call the right people" },
      { type: "p", text: "Performance also depends on who is called first. If hot leads sit in the same list as cold ones, a good telecaller still wastes hours. In Anril, hot leads from WhatsApp, Instagram and Facebook are assigned to a telecaller automatically, with the conversation on screen before the call." },
    ],
    faqs: [
      { q: "How often should I review telecaller performance?", a: "Look at activity numbers weekly and review a few scored calls with each telecaller in a short weekly one-to-one." },
      { q: "Does CallIQ understand Tamil?", a: "Yes. CallIQ understands Tamil calls. Calls and recordings are unlimited." },
      { q: "How is CallIQ billed?", a: "Yearly, from ₹14,999 a year." },
    ],
  },
  {
    slug: "real-estate-lead-management-whatsapp",
    seoTitle: "Real Estate Lead Management on WhatsApp",
    title: "Lead management for real estate: stop losing buyers on WhatsApp",
    description:
      "Property buyers message several builders at once. Here is how real estate teams answer fast, qualify buyers and call the hot ones first on WhatsApp.",
    published: "2026-11-02",
    updated: "2026-11-02",
    author: BLOG_AUTHOR,
    link: { href: "/industries/real-estate", label: "Anril for real estate" },
    body: [
      { type: "p", text: "Real estate teams lose buyers on WhatsApp for three reasons: the reply comes late, nobody asks the right questions, and the hot buyers are buried among casual ones. Fixing those three things matters more than getting more enquiries." },
      { type: "h2", text: "Why speed matters" },
      { type: "p", text: "A buyer looking for a 2 BHK usually messages several builders and agents in the same evening. The first useful reply tends to win the site visit. Enquiries also arrive at night and at weekends, when your sales team is not at their desks. An AI chatbot that answers in seconds, at any hour, keeps the buyer talking to you." },
      { type: "h2", text: "Ask the right questions early" },
      { type: "p", text: "Before a sales executive spends time on a buyer, you want to know three things: budget, location and BHK. A chatbot can ask these in the first few messages and remember the answers, so the executive starts the call already knowing what the buyer wants." },
      { type: "h2", text: "Separate hot, warm and cold buyers" },
      { type: "p", text: "A buyer who asks for a site visit on Saturday is not the same as a buyer who asked about the price and went quiet. Anril scores every lead Hot, Warm or Cold from the conversation, and updates the score with each new message. Hot buyers go to a sales executive to call straight away. Warm and cold buyers are followed up automatically." },
      { type: "h2", text: "Put every source in one list" },
      { type: "p", text: "Property enquiries arrive from WhatsApp, Instagram and Facebook. When each lives in a different place, buyers fall through the gaps. Anril puts all of them in one lead list with the whole conversation attached." },
      { type: "h2", text: "A simple weekly routine" },
      { type: "ul", items: ["Check the hot list every morning and call every hot buyer that day.", "Review warm buyers twice a week and share new inventory with them.", "Look at which source brought the buyers who booked visits.", "Update the information the chatbot uses when prices, availability or visit timings change."] },
    ],
    faqs: [
      { q: "Can the chatbot book site visits?", a: "It can offer visit slots in the chat. When a buyer books a visit, the lead is marked hot and sent to a sales executive to call." },
      { q: "Does it work at night?", a: "Yes. It answers every enquiry as soon as it arrives, including nights, weekends and holidays." },
      { q: "How much does it cost?", a: "Plans start from ₹999 a month (plus GST)." },
    ],
  },
  {
    slug: "hot-warm-cold-lead-scoring",
    seoTitle: "Hot, Warm, Cold: Score WhatsApp Leads Simply",
    title: "Hot, Warm, Cold: a simple way to score leads from WhatsApp",
    description:
      "Score every WhatsApp lead Hot, Warm or Cold so your team calls the right person first. Learn what each score means and how to keep scoring accurate.",
    published: "2026-11-02",
    updated: "2026-11-02",
    author: BLOG_AUTHOR,
    link: { href: "/whatsapp-crm", label: "Anril's WhatsApp CRM with lead scoring" },
    body: [
      { type: "p", text: "Lead scoring means marking each lead by how ready they are to buy, so your team starts with the people most likely to say yes. The simplest version has three levels: Hot, Warm and Cold. It is easy to understand, easy to act on, and works well for businesses that get many enquiries on WhatsApp." },
      { type: "h2", text: "What the three scores mean" },
      { type: "ul", items: ["Hot: the lead has taken a buying step, for example asked for a visit, a quote, a test drive or a call back. Contact them today.", "Warm: the lead is interested and asking questions but has not taken a buying step. Follow up and keep the conversation going.", "Cold: the lead sent a general message or has gone quiet. Keep them in a gentle follow-up, and do not spend your best time here."] },
      { type: "h2", text: "Decide what a buying step is in your business" },
      { type: "p", text: "The score only helps if it reflects how your customers really buy. A school's buying step might be asking for a campus visit. A clinic's might be asking for an appointment slot. A manufacturer's might be asking for a quote. Anril lets you describe what a buying step looks like in your business, and the scoring follows it." },
      { type: "h2", text: "Let the score move" },
      { type: "p", text: "A lead is not hot or cold forever. Someone cold on Monday can ask for a visit on Thursday. Anril updates the mark whenever the lead sends a new message, so the list always shows who to call first right now." },
      { type: "h2", text: "What to do with each score" },
      { type: "ul", items: ["Hot: assign to a person immediately, with the conversation on screen.", "Warm: send helpful information and a follow-up within a day or two.", "Cold: automatic follow-ups at a slower pace."] },
      { type: "h2", text: "Common mistakes" },
      { type: "ul", items: ["Scoring only by how many messages a lead sent. Length of chat is not intent.", "Never rechecking: a stale Hot list teaches your team to ignore it.", "Using too many levels. Three is enough to act on.", "Not telling the team what each score means."] },
    ],
    faqs: [
      { q: "Who scores the leads in Anril?", a: "Anril's AI scores each lead from what they asked and how they answered, and updates the score with every new message." },
      { q: "Can I define what counts as a hot lead?", a: "Yes. You describe what a buying step looks like in your business, and the scoring follows that." },
      { q: "How much does it cost?", a: "Plans start from ₹999 a month (plus GST)." },
    ],
  },
  {
    slug: "whatsapp-business-api-pricing-india",
    seoTitle: "WhatsApp Business API Pricing in India (2026)",
    title: "WhatsApp Business API pricing in India (2026): what you actually pay",
    description:
      "How WhatsApp Business API pricing works in India: Meta charges per delivered message by category, plus your provider's plan. What's free, with an example.",
    published: "2026-11-02",
    updated: "2026-11-02",
    author: BLOG_AUTHOR,
    link: { href: "/pricing", label: "Anril plans from ₹999 a month" },
    body: [
      { type: "p", text: "WhatsApp Business API pricing in India has two parts: Meta's charge for each message delivered, and your provider's monthly plan. Meta charges per delivered message, and the rate depends on the message category and the country of the person you message. The provider's plan, for example Anril's from ₹999 a month (plus GST), is separate." },
      { type: "h2", text: "Part 1: what Meta charges" },
      { type: "p", text: "Meta charges for each business message that is delivered. If a message is not delivered, you are not charged. Messages that customers send to you are free. The rate depends on the message category:" },
      { type: "ul", items: ["Marketing: offers, promotions and announcements. This is the most expensive category.", "Utility: messages about something the customer did, such as an order update or a booking confirmation.", "Authentication: one-time passwords and login codes.", "Service: replies to a customer who messaged you first, sent inside the 24-hour customer service window."] },
      { type: "p", text: "Marketing, utility and authentication messages are sent as approved templates and can be sent at any time. Service messages are not templates and can only be sent inside the 24-hour window that opens when the customer messages you." },
      { type: "h2", text: "What is free" },
      { type: "ul", items: ["Messages that customers send to your business.", "Each business phone number gets 1,000 free service messages a month. They do not roll over.", "When a customer messages you by tapping a Click to WhatsApp ad, a free entry point window opens (Meta says up to 7 days), and your messages in that window are free."] },
      { type: "p", text: "Meta has changed these rules several times, and one change took effect on 1 October 2026: utility templates sent inside an open customer service window used to be free and are now charged, except inside a free entry point window. Always check Meta's current rules before you budget." },
      { type: "h2", text: "Where to find the current rates in India" },
      { type: "p", text: "Meta publishes the exact rates for each country in its rate card, and they change from time to time. Marketing is the most expensive category, and Meta raised the India marketing rate on 1 January 2026. Check the current rupee rates on Meta's rate card, or ask your provider, before you plan. Rates exclude GST, and a provider may add its own markup." },
      { type: "p", text: "Meta also now bills Indian businesses in rupees. Eligible accounts must move to INR billing by 31 December 2026." },
      { type: "h2", text: "Part 2: your provider's plan" },
      { type: "p", text: "A provider connects you to the API and gives you the tools to use it: campaigns, a shared inbox, chatbot and reports. Plans vary in what they include and how they count usage. Anril plans start from ₹999 a month (plus GST), or ₹799 a month on a yearly plan. Only AI replies are counted, not customer messages, and WhatsApp message charges from Meta are billed separately." },
      { type: "h2", text: "A worked example" },
      { type: "p", text: "Say you send a marketing campaign to 5,000 contacts and 4,800 messages are delivered. Your Meta cost is 4,800 multiplied by the current marketing rate. Customers who reply start a 24-hour window, and your answers inside that window are service messages, which count towards the 1,000 free service messages a month. Your provider's plan is added on top, plus GST." },
      { type: "h2", text: "How to keep WhatsApp costs down" },
      { type: "ul", items: ["Send marketing messages only to people who want them, since you pay for every delivered message.", "Segment your list so each message is relevant and gets replies.", "Use Click to WhatsApp ads, because the free entry point window makes the first conversation free.", "Answer replies inside the 24-hour window with service messages instead of sending new templates."] },
    ],
    faqs: [
      { q: "Is WhatsApp Business API free?", a: "No. Meta charges for delivered business messages, by category, and a provider charges for its plan. Messages customers send you are free, and each number gets 1,000 free service messages a month." },
      { q: "Does Anril's price include WhatsApp message charges?", a: "No. WhatsApp message charges from Meta are billed separately from the Anril plan." },
      { q: "How much does Anril cost?", a: "Plans start from ₹999 a month (plus GST), or ₹799 a month on a yearly plan." },
    ],
  },
  {
    slug: "instagram-auto-dm-reply-automatically",
    seoTitle: "Instagram Auto DM: Reply to Every Message",
    title: "Instagram auto DM: how to reply to every Instagram message automatically",
    description:
      "Instagram auto DM replies answer customer messages in seconds, even at night. Learn what automation can do, what to avoid, and how to hand over to a person.",
    published: "2026-11-02",
    updated: "2026-11-02",
    author: BLOG_AUTHOR,
    link: { href: "/whatsapp-chatbot", label: "Anril's AI chatbot for WhatsApp, Instagram and Facebook" },
    body: [
      { type: "p", text: "An Instagram auto DM replies to customer messages automatically, so a person who messages your business gets an answer in seconds instead of hours. The best setups go beyond a fixed greeting: an AI assistant answers real questions from your business information, finds out what the customer wants, and passes serious buyers to your team." },
      { type: "h2", text: "Why replying fast matters on Instagram" },
      { type: "p", text: "People who message a business on Instagram are usually browsing several options at once. A reply that arrives the next morning often arrives after they have chosen someone else. Many messages also come in the evening and at weekends, when your team is offline." },
      { type: "h2", text: "Three kinds of Instagram auto-reply" },
      { type: "ul", items: ["Away message: a fixed note such as \"we will reply soon\". It is better than silence but answers nothing.", "Menu or keyword replies: the customer picks an option, or types a word, and gets a fixed answer. Good for a short list of questions, and frustrating for anything else.", "AI replies: an assistant reads the customer's real message and answers from the information you gave it. This is what Anril does for Instagram DMs."] },
      { type: "h2", text: "What a good AI reply setup does" },
      { type: "ul", items: ["Answers questions about your products, prices, timings and location in seconds, at any hour.", "Replies in the customer's language. Anril replies in Tanglish by default and can use any language.", "Scores each lead Hot, Warm or Cold, so you can see who is ready to buy.", "Hands the chat to a person, with everything said so far, when the customer needs one.", "Keeps Instagram, WhatsApp and Facebook enquiries in one list."] },
      { type: "h2", text: "Mistakes to avoid" },
      { type: "ul", items: ["Pretending the assistant is a person. If a customer asks, Anril says it is an AI assistant.", "Setting up automation and never checking it. Review the conversations regularly and update the information the assistant uses.", "Having no handover. Customers who want a person should reach one easily.", "Treating Instagram as separate from your other channels, so leads get lost."] },
      { type: "h2", text: "How to set it up with Anril" },
      { type: "p", text: "Connect your Instagram business account to Anril, add your business information to the knowledge base, and the AI starts replying to DMs. You can edit the information at any time, and the change works instantly. Book a free demo and we will set it up with questions like the ones your customers really ask." },
    ],
    faqs: [
      { q: "Can I auto-reply to Instagram DMs for free?", a: "Instagram offers basic saved replies and away messages for business accounts. For AI replies that answer real questions and score leads, you need a tool such as Anril, with plans from ₹999 a month (plus GST)." },
      { q: "Does Anril work on Instagram?", a: "Yes. Anril replies to enquiries on WhatsApp, Instagram DMs and Facebook Messenger." },
      { q: "Will customers know it is an AI?", a: "If a customer asks, Anril's chatbot says it is an AI assistant." },
    ],
  },
];

/** Published articles only. */
export const POSTS: readonly Post[] = ALL_POSTS.filter((p) => !p.draft);

export function findPost(slug: string): Post | undefined {
  return POSTS.find((p) => p.slug === slug);
}

export function postPath(slug: string): string {
  return `/blog/${slug}`;
}
