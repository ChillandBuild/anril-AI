import type { FaqEntry } from "./schema";

// Copy for the product pages (/whatsapp-chatbot ...) and the industry pages (/industries/real-estate ...).
// Every statement is a fact about Anril AI from the SEO brief (29 Oct 2026), llms.txt or the product itself.
// Anything not decided yet (Commerce and Attract prices, payment methods) is deliberately left out.

export type Landing = {
  slug: string;
  /** Public path, e.g. "/whatsapp-chatbot" or "/industries/real-estate". */
  path: string;
  kicker: string;
  /** Short name used in menus, breadcrumbs and related links. */
  label: string;
  title: string;
  description: string;
  h1: string;
  /** The answer, directly under the H1. This is the text search and AI answers quote. */
  opening: string;
  sections: readonly { h: string; p: readonly string[] }[];
  faqs: readonly FaqEntry[];
  /** Slugs of two related pages. */
  related: readonly string[];
  /** Where the "plans" link in the page's closing band points. */
  priceNote?: string;
  /** Only for industry pages: an example conversation, shown marked as an example. */
  example?: { q: string; r: string; outcome: string };
};

export const PRODUCT_PAGES: readonly Landing[] = [
  {
    slug: "whatsapp-chatbot",
    path: "/whatsapp-chatbot",
    kicker: "Engage",
    label: "WhatsApp AI chatbot",
    title: "WhatsApp AI Chatbot for Business – Replies in Tanglish | Anril AI",
    description:
      "Anril's WhatsApp AI chatbot replies to every enquiry in seconds, day and night, in Tanglish or any language, and scores leads Hot, Warm or Cold. From ₹999/month.",
    h1: "WhatsApp AI chatbot that replies to every enquiry",
    opening:
      "Anril's WhatsApp AI chatbot answers customer enquiries on WhatsApp, Instagram and Facebook in seconds, using your own business information. It replies in Tanglish by default, understands voice notes, scores each lead Hot, Warm or Cold, and hands over to your team when needed.",
    sections: [
      {
        h: "What can the Anril chatbot answer?",
        p: [
          "It answers from the information you give it about your business: your services, prices, timings, locations, policies and the questions your customers ask most. You keep that information in a knowledge base, and the chatbot uses it for every reply.",
          "The chatbot can also send photos and price lists in the chat. It cannot read images that customers send to it.",
          "Because it answers every enquiry as soon as it arrives, customers who message at night, on a Sunday or on a holiday get a reply in seconds instead of waiting for the morning.",
        ],
      },
      {
        h: "Does it reply in Tamil and Tanglish?",
        p: [
          "Yes. Anril replies in Tanglish, Tamil written in English letters, by default, because that is how many customers in Tamil Nadu type on WhatsApp. It can also reply in any other language your customers use. It understands voice notes too, so a customer who records a message instead of typing still gets an answer.",
        ],
      },
      {
        h: "How does it tell me who is ready to buy?",
        p: [
          "While it chats, Anril scores every lead Hot, Warm or Cold from what the customer asked and how they answered. The score updates every time the lead sends a new message. You describe what a buying step looks like in your business, for example asking for a site visit, a fee quote or a test drive, and the scoring follows that.",
          "Hot leads reach your team first, and the chatbot follows up with leads automatically so that a warm enquiry does not go quiet.",
        ],
      },
      {
        h: "What happens when a customer wants to talk to a person?",
        p: [
          "The chat is handed over to your team with everything that was said so far, so nobody has to ask the customer to repeat themselves. Your team then continues the conversation from the same place. If a customer asks whether they are talking to an AI, the chatbot says that it is an AI assistant.",
        ],
      },
      {
        h: "How do I teach it about my business?",
        p: [
          "You add your business information to the knowledge base, and you can edit it at any time. A change works instantly, so a new offer or a changed timing is used in the very next reply. During a free demo we set it up with questions like the ones your own customers ask.",
        ],
      },
    ],
    faqs: [
      { q: "Does the chatbot work at night and on holidays?", a: "Yes. It replies to every enquiry as soon as it arrives." },
      { q: "Can it send photos and price lists?", a: "Yes, it can send photos and price lists. It can't read images that customers send." },
      { q: "Will customers know it's an AI?", a: "If a customer asks, it says it's an AI assistant." },
      { q: "Can I change what it says?", a: "Yes. You edit your knowledge base anytime, and the change works instantly." },
      { q: "How much does it cost?", a: "Plans start from ₹999 a month (plus GST). Only AI replies are counted, not customer messages." },
    ],
    related: ["whatsapp-crm", "bulk-whatsapp-sender"],
  },
  {
    slug: "bulk-whatsapp-sender",
    path: "/bulk-whatsapp-sender",
    kicker: "Reach",
    label: "Bulk WhatsApp sender",
    title: "Bulk WhatsApp Sender & Marketing Software (Official API) | Anril AI",
    description:
      "Send WhatsApp offers and updates to your whole customer list with approved templates, scheduling and delivery reports. Official WhatsApp API. From ₹999/month.",
    h1: "Bulk WhatsApp marketing, the safe and official way",
    opening:
      "Anril Reach lets you send WhatsApp campaigns to your customer lists using Meta-approved templates. You can split contacts into groups, schedule messages, and see who received, read and replied, all from one dashboard.",
    sections: [
      {
        h: "How do I send bulk WhatsApp messages without getting blocked?",
        p: [
          "Send them through the official WhatsApp Business API, which is what Anril Reach uses, rather than through unofficial tools that push messages out from a normal number. Campaigns use templates that Meta has approved, and you send them to customers you have contact details for. Staying on the official route is what keeps a number safe.",
        ],
      },
      {
        h: "What is an approved WhatsApp template?",
        p: [
          "A template is a message whose wording Meta has reviewed in advance, such as an offer, an event reminder or an update. Business-started messages on WhatsApp go out as approved templates. Anril lets you create and use them, so a campaign can be sent as soon as its template is approved.",
        ],
      },
      {
        h: "Can I schedule WhatsApp campaigns?",
        p: [
          "Yes. You can split your contacts into lists and segments, so the right message goes to the right customers, and you can schedule a campaign to go out at a time you choose. Afterwards, delivery and engagement reports show who received the message, who read it and who replied.",
        ],
      },
      {
        h: "What happens when customers reply?",
        p: [
          "Anril's AI chatbot replies instantly and scores the lead, so a customer who answers a campaign is not left waiting. Hot leads reach your team first. Campaigns, replies and leads sit in the same platform, so you can see what each campaign brought in.",
        ],
      },
    ],
    faqs: [
      { q: "Is this the official WhatsApp API?", a: "Yes. Campaigns go through Meta's official WhatsApp Business API." },
      {
        q: "Can I use my existing number?",
        a: "Yes, your number can be connected. If you don't need bulk campaigns, you can keep using the WhatsApp Business app instead.",
      },
      {
        q: "Who replies when customers answer a campaign?",
        a: "Anril's AI chatbot replies instantly and scores the lead, so hot leads reach your team first.",
      },
      { q: "Are WhatsApp message charges included?", a: "No. Meta charges for messages separately from the Anril plan." },
      {
        q: "How much does it cost?",
        a: "Reach plans start from ₹999 a month (plus GST), with 2 users and 1,000 AI replies on the Starter plan.",
      },
    ],
    related: ["whatsapp-chatbot", "whatsapp-crm"],
  },
  {
    slug: "whatsapp-crm",
    path: "/whatsapp-crm",
    kicker: "Engage",
    label: "WhatsApp CRM",
    title: "WhatsApp CRM & Lead Management System | Anril AI",
    description:
      "Every WhatsApp, Instagram and Facebook enquiry in one list, scored Hot, Warm or Cold, with follow-ups and team handover. Know who to call first. From ₹999/month.",
    h1: "WhatsApp CRM that tells you who to call first",
    opening:
      "Anril puts every enquiry from WhatsApp, Instagram and Facebook into one lead list. The AI scores each lead Hot, Warm or Cold based on the conversation, follows up automatically, and passes hot leads to the right person on your team.",
    sections: [
      {
        h: "What is a WhatsApp CRM?",
        p: [
          "A CRM keeps track of your customers and leads. A WhatsApp CRM does this where the conversations actually happen. Instead of copying numbers from WhatsApp into a spreadsheet, every enquiry that arrives on WhatsApp, Instagram or Facebook becomes a lead in one list, with the whole conversation attached to it.",
        ],
      },
      {
        h: "How does Hot, Warm, Cold lead scoring work?",
        p: [
          "Anril reads the conversation and marks the lead Hot, Warm or Cold from what the person asked and how they answered. Someone who asks to book a visit or requests a quote is marked hot. Someone who only asked a general question stays warm or cold. The mark updates whenever the lead sends a new message, so the list always shows who to call first.",
          "You describe what a buying step looks like in your business, and the scoring follows that.",
        ],
      },
      {
        h: "How do follow-ups work?",
        p: [
          "Anril follows up with leads automatically, so an enquiry that went quiet is not forgotten. When a lead needs a person, the conversation is handed to the right member of your team along with everything said so far.",
        ],
      },
      {
        h: "Can my whole team use it?",
        p: [
          "Yes. Plans include more than one user (the Starter plan has 2 users), and conversation and team reports show how work is going. Leads, conversations, payments and orders are kept together, so the person who picks up a lead sees its full history.",
        ],
      },
    ],
    faqs: [
      { q: "Do I need a separate CRM?", a: "No. Leads, conversations, payments and orders are kept together in Anril." },
      { q: "Can I see my team's performance?", a: "Yes. Anril shows conversation and team reports." },
      { q: "Does it work on mobile?", a: "It runs in the browser. A mobile app is also available with limited features." },
      { q: "How much does it cost?", a: "Plans start from ₹999 a month (plus GST)." },
    ],
    related: ["whatsapp-chatbot", "telecaller-software"],
  },
  {
    slug: "telecaller-software",
    path: "/telecaller-software",
    kicker: "CallIQ",
    label: "Telecaller software",
    title: "Telecaller Software with Tamil Call Analysis | Anril CallIQ",
    description:
      "Record every sales call, understand Tamil conversations and measure each telecaller's performance. Unlimited calls and recording. Built in Coimbatore.",
    h1: "Telecaller software that understands Tamil calls",
    opening:
      "Anril CallIQ records your team's sales calls, understands Tamil conversations, and shows how each telecaller is performing. Hot leads from WhatsApp go straight to a telecaller, so your team calls the right people first.",
    sections: [
      {
        h: "How do I track telecaller performance?",
        p: [
          "Every telecaller call is recorded and scored, so you can see who is closing and who needs help. Owners and managers review the scored calls in one place instead of listening to calls one by one. CallIQ also shows call timing and productivity for each telecaller.",
        ],
      },
      {
        h: "Can it understand Tamil calls?",
        p: [
          "Yes. CallIQ is built to understand Tamil conversations. The call analysis shows call quality and insights from what was actually said.",
        ],
      },
      {
        h: "How do telecallers know who to call?",
        p: [
          "Chat and calls are linked. Hot leads from WhatsApp, Instagram and Facebook are assigned to a telecaller automatically, and the telecaller sees what the lead asked and what was said before picking up the phone. The call continues from where the chat ended, and the follow-up stays in the same place.",
        ],
      },
      {
        h: "Are calls recorded?",
        p: ["Yes. Calls are recorded, and there is no limit on the number of calls or recordings."],
      },
    ],
    faqs: [
      { q: "Is there a limit on calls or recordings?", a: "No. Calls and recordings are unlimited." },
      { q: "How is CallIQ billed?", a: "Yearly, from ₹14,999 a year." },
    ],
    related: ["whatsapp-crm", "whatsapp-chatbot"],
  },
  {
    slug: "whatsapp-payments",
    path: "/whatsapp-payments",
    kicker: "Commerce",
    label: "WhatsApp payments and orders",
    title: "WhatsApp Payments, Orders & Stock in One Place | Anril AI",
    description:
      "Send Razorpay payment links on WhatsApp, turn chats into orders, track stock and dispatch, all with your enquiries in one dashboard.",
    h1: "Take payments and orders right from the chat",
    opening:
      "Anril Commerce lets you send payment links in WhatsApp chats, see payment status, create orders from enquiries, manage your catalogue and stock with low-stock alerts, and track dispatch, all in the same place as your conversations.",
    sections: [
      {
        h: "How do I take a payment on WhatsApp?",
        p: [
          "When a customer is ready to buy, a payment link is sent in the chat. The link goes through Razorpay, and you can see the payment status without leaving Anril. Payment links can be sent automatically, so nobody has to type them out by hand.",
        ],
      },
      {
        h: "Can a chat become an order?",
        p: [
          "Yes. A customer can order in the chat, and the order is created from that enquiry. It is then tracked from order to payment to dispatch, and the order and invoice sit alongside the conversation that led to them.",
        ],
      },
      {
        h: "What about the catalogue and stock?",
        p: [
          "You can keep your catalogue and stock in Anril. When an order is placed the stock is updated, and low-stock alerts warn you before an item runs out. Dispatch status shows which orders have gone out.",
        ],
      },
    ],
    faqs: [
      { q: "Which payment gateway is used?", a: "Razorpay." },
      { q: "Do I get GST invoices?", a: "Yes." },
      { q: "How much does it cost?", a: "Book a demo for pricing." },
    ],
    related: ["whatsapp-chatbot", "whatsapp-crm"],
  },
  {
    slug: "social-media-ads",
    path: "/social-media-ads",
    kicker: "Anril Attract",
    label: "Social media and ads",
    title: "Done-for-You Social Media & Ads with WhatsApp Leads | Anril Attract",
    description:
      "We run your Instagram and Facebook posts plus Meta and Google ads, and every lead goes straight into Anril's AI chat. Built in Coimbatore.",
    h1: "We bring the leads. Anril answers them.",
    opening:
      "Anril Attract is a done-for-you service: we create and post your Instagram and Facebook content and run your Meta and Google ads. Every lead lands in Anril's AI chat, which replies instantly and tells you who's ready to buy.",
    sections: [
      {
        h: "What does Anril Attract do?",
        p: [
          "Our team creates and posts content for your Instagram and Facebook pages, and runs your advertising on Meta and Google. You do not have to manage the posting or the ads yourself.",
        ],
      },
      {
        h: "What happens to the leads?",
        p: [
          "Every enquiry that comes from your posts and ads lands in Anril's AI chat. It replies in seconds, in Tanglish or any language, scores the lead Hot, Warm or Cold, and passes hot leads to your team. You see which enquiries are ready to buy instead of a long list of unanswered messages.",
        ],
      },
      {
        h: "Why combine ads and AI replies?",
        p: [
          "Most of the value of an ad is lost if the enquiry it creates waits hours for an answer. Because the same platform that brings the leads also answers them, a customer who messages from an ad gets a reply straight away, including at night.",
        ],
      },
    ],
    faqs: [
      {
        q: "Is the ad budget included?",
        a: "No. The ad budget is separate and paid to Meta or Google directly. Our team will explain it.",
      },
      { q: "Who is it for?", a: "Any Anril client. We're starting with education consultancies." },
      { q: "How much does it cost?", a: "Talk to us. We'll explain the options on a call." },
    ],
    related: ["whatsapp-chatbot", "bulk-whatsapp-sender"],
  },
];

export const INDUSTRY_PAGES: readonly Landing[] = [
  {
    slug: "real-estate",
    path: "/industries/real-estate",
    kicker: "Real estate",
    label: "Real estate",
    title: "Real Estate Lead Management & WhatsApp Chatbot | Anril AI",
    description:
      "Anril answers property enquiries on WhatsApp instantly, scores each buyer Hot, Warm or Cold, and sends hot buyers to your sales team. From ₹999/month.",
    h1: "Real estate lead management on WhatsApp",
    opening:
      "Anril answers property enquiries on WhatsApp instantly, asks budget, location and BHK, scores the buyer Hot, Warm or Cold, and sends hot buyers to your sales team.",
    sections: [
      {
        h: "What do property buyers ask?",
        p: [
          "Buyers ask about prices, floor plans, site visits and home loans, often outside office hours and often to several builders at once. The one who replies first is usually the one who gets the visit.",
        ],
      },
      {
        h: "How does Anril handle a property enquiry?",
        p: [
          "It replies in seconds from the project information you give it, asks what the buyer needs, such as budget, location and BHK, and offers a site visit slot. When a buyer books a visit, the lead is marked hot and sent to a sales executive to call, with the whole chat on screen.",
          "Buyers who are only browsing stay warm or cold, and Anril follows up with them automatically, so your sales team spends its time on the buyers who are ready.",
        ],
      },
      {
        h: "Where do the leads come from?",
        p: [
          "Enquiries from WhatsApp, Instagram and Facebook arrive in one list. If you run property ads, Anril Attract can run them for you, and the leads go straight into the same AI chat.",
        ],
      },
    ],
    faqs: [
      { q: "Can it answer questions about my projects at night?", a: "Yes. It answers every enquiry as soon as it arrives, including nights, weekends and holidays." },
      { q: "How does it decide a buyer is hot?", a: "It scores each lead from what they asked and how they answered. Asking to book a site visit marks a buyer hot, and the mark updates with every new message." },
      { q: "How much does it cost?", a: "Plans start from ₹999 a month (plus GST). Book a demo to see it with your own project details." },
    ],
    related: ["education", "d2c"],
    example: {
      q: "Is the 2 BHK still available? Can I visit on Saturday?",
      r: "Yes, 2 BHK homes are still available. Site visits on Saturday run from 10 am. Shall I book you a slot?",
      outcome: "Marked hot after booking a visit, and sent to a sales executive to call.",
    },
  },
  {
    slug: "education",
    path: "/industries/education",
    kicker: "Education",
    label: "Education",
    title: "WhatsApp Chatbot for Schools & Colleges | Anril AI",
    description:
      "Anril replies to admission and course enquiries day and night, shares fees and brochures, and passes serious students and parents to your counsellors.",
    h1: "WhatsApp chatbot for schools and colleges",
    opening:
      "Anril replies to admission and course enquiries day and night, shares fees and brochures, and passes serious students and parents to your counsellors.",
    sections: [
      {
        h: "What do students and parents ask?",
        p: [
          "They ask about course fees, batch timings, admission dates and campus visits. Many of these questions arrive in the evening, when parents are free, and the same questions come in again and again.",
        ],
      },
      {
        h: "How does Anril help an admissions team?",
        p: [
          "It answers the repeated questions at once, from the information you give it, and offers a campus visit. A student or parent who asks to visit is marked hot and sent to a counsellor to call, with the chat in front of them. Casual questions stay warm or cold and are followed up automatically.",
          "Study-abroad consultants have their own page, with the questions students and parents ask them.",
        ],
      },
      {
        h: "Can it run campaigns for admissions?",
        p: [
          "Yes. Anril Reach sends WhatsApp campaigns to your contact lists with approved templates, and Anril Attract, which we are starting with education consultancies, can run your Instagram, Facebook and Google ads and send the leads into the AI chat.",
        ],
      },
    ],
    faqs: [
      { q: "Does it reply in Tamil?", a: "Yes. It replies in Tanglish by default and can reply in any language. It also understands voice notes." },
      { q: "Can it share fees and brochures?", a: "Yes. It can send photos and price lists, and answers fee questions from the information you give it." },
      { q: "How much does it cost?", a: "Plans start from ₹999 a month (plus GST)." },
    ],
    related: ["study-abroad", "healthcare"],
    example: {
      q: "What are the fees for the weekend batch?",
      r: "The weekend batch starts next month, on Saturday and Sunday mornings. I can share the fee details and book you a campus visit. Which day suits you?",
      outcome: "Marked hot after asking to visit, and sent to a counsellor to call.",
    },
  },
  {
    slug: "study-abroad",
    path: "/industries/study-abroad",
    kicker: "Study abroad",
    label: "Study-abroad consultants",
    title: "WhatsApp Chatbot & Lead Management for Study Abroad Consultants | Anril AI",
    description:
      "Anril replies to study-abroad enquiries on WhatsApp day and night, scores each student Hot, Warm or Cold, and passes serious students to your counsellors.",
    h1: "WhatsApp chatbot and lead management for study-abroad consultants",
    opening:
      "Anril replies to students' and parents' study-abroad enquiries on WhatsApp, Instagram and Facebook at any hour, scores each lead Hot, Warm or Cold, and passes serious students to your counsellors with the whole chat.",
    sections: [
      {
        h: "What do students and parents ask a study-abroad consultant?",
        p: [
          "They ask about countries, courses, intakes, fees and what is needed to apply. Many of these messages arrive in the evening or at the weekend, when your counsellors are offline, and the same questions come in again and again.",
        ],
      },
      {
        h: "How does Anril help your counsellors?",
        p: [
          "It answers the repeated questions at once, from the information you give it, and asks what the student is looking for. A student who asks for a call with a counsellor is marked hot and passed to a counsellor, with the whole chat in front of them. Students who are only browsing stay warm or cold and are followed up automatically.",
          "Your counsellors spend their time on the students who are serious, instead of answering the same first questions all day.",
        ],
      },
      {
        h: "Can Anril also bring in more enquiries?",
        p: [
          "Yes. Anril Attract is a done-for-you service that we are starting with education consultancies: we run your Instagram and Facebook posts and your Meta and Google ads, and every lead lands in Anril's AI chat. The ad budget is separate and paid to Meta or Google directly.",
          "Anril Reach sends WhatsApp campaigns to your contact lists using approved templates, with delivery and engagement reports afterwards.",
        ],
      },
    ],
    faqs: [
      { q: "Does it reply in Tamil?", a: "Yes. It replies in Tanglish by default and can reply in any language. It also understands voice notes." },
      { q: "Who talks to the student after the AI?", a: "Your counsellors. Anril passes the chat to your team along with everything said so far." },
      { q: "Can it send photos and price lists?", a: "Yes, it can send photos and price lists. It can't read images that students send." },
      { q: "How much does it cost?", a: "Plans start from ₹999 a month (plus GST). Book a demo to see it with your own questions." },
    ],
    related: ["education", "healthcare"],
    example: {
      q: "Can I get details about courses in Canada for the next intake?",
      r: "Yes, I can share the options and what you need to apply. Which course are you interested in? I can also book you a call with a counsellor.",
      outcome: "Marked hot after asking for a counsellor call, and passed to a counsellor.",
    },
  },
  {
    slug: "healthcare",
    path: "/industries/healthcare",
    kicker: "Healthcare",
    label: "Healthcare",
    title: "WhatsApp Chatbot for Hospitals & Clinics | Anril AI",
    description:
      "Anril answers patient enquiries on WhatsApp about doctors, timings and services, and sends appointment requests to your front desk.",
    h1: "WhatsApp chatbot for hospitals and clinics",
    opening:
      "Anril answers patient enquiries on WhatsApp about doctors, timings and services, and sends appointment requests to your front desk.",
    sections: [
      {
        h: "What do patients ask?",
        p: [
          "Patients ask whether a doctor is available, which slots are free, what a service costs and how to reach the clinic. These questions tie up a front desk that is also dealing with people in the building.",
        ],
      },
      {
        h: "How does Anril help the front desk?",
        p: [
          "It answers doctor availability, timings, services and directions from the information you give it, at any hour. When a patient asks for an appointment, the request is marked hot and passed to the front desk to confirm. Its job is to answer the practical questions and hand appointments to your team.",
        ],
      },
      {
        h: "Can it send updates to patients?",
        p: [
          "Anril Reach can send WhatsApp campaigns and updates to your contact lists using Meta-approved templates, with delivery and engagement reports afterwards.",
        ],
      },
    ],
    faqs: [
      { q: "Does it work outside clinic hours?", a: "Yes. It replies to every enquiry as soon as it arrives, so patients get an answer at night too." },
      { q: "Who confirms the appointment?", a: "Your front desk. Anril passes the request to your team along with the conversation." },
      { q: "How much does it cost?", a: "Plans start from ₹999 a month (plus GST)." },
    ],
    related: ["education", "real-estate"],
    example: {
      q: "Is the doctor available tomorrow evening?",
      r: "Yes, the doctor sees patients from 5 pm to 8 pm tomorrow. Would you like me to request a slot?",
      outcome: "Marked hot after asking for a slot, and passed to the front desk to confirm.",
    },
  },
  {
    slug: "d2c",
    path: "/industries/d2c",
    kicker: "D2C brands",
    label: "D2C brands",
    title: "WhatsApp Chatbot, Payments & Orders for D2C Brands | Anril AI",
    description:
      "Anril replies to product questions, sends photos and price lists, collects payment by link and creates the order, all inside the WhatsApp chat.",
    h1: "WhatsApp chatbot, payments and orders for D2C brands",
    opening:
      "Anril replies to product questions, sends photos and price lists, collects payment by link and creates the order, all inside the WhatsApp chat.",
    sections: [
      {
        h: "What do shoppers ask a D2C brand?",
        p: [
          "They ask about products, sizes, prices, delivery and availability, usually on Instagram or WhatsApp, and usually at the moment they are deciding to buy.",
        ],
      },
      {
        h: "How does Anril take a customer from question to order?",
        p: [
          "It answers the product question from your catalogue information, sends photos and the price list, and when the customer is ready it sends a Razorpay payment link in the chat. Once the payment is made, the order is created from that conversation, and stock and dispatch status are tracked in Anril.",
        ],
      },
      {
        h: "How do I tell shoppers about a new offer?",
        p: [
          "With Anril Reach you can send an offer to your customer lists as a WhatsApp campaign using an approved template. Anril's AI chatbot replies to the customers who respond, so the campaign leads into a conversation and then an order.",
        ],
      },
    ],
    faqs: [
      { q: "Can customers pay inside the chat?", a: "Yes. A Razorpay payment link is sent in the chat, and you can see the payment status in Anril." },
      { q: "Does it track stock?", a: "Yes. Anril keeps your catalogue and stock, and low-stock alerts warn you before an item runs out." },
      { q: "How much does it cost?", a: "Plans start from ₹999 a month (plus GST). Book a demo for Commerce pricing." },
    ],
    related: ["real-estate", "education"],
    example: {
      q: "Do you have this kurta in medium? What is the price?",
      r: "Yes, it is available in medium. Here are photos and the price list. Would you like a payment link to order it now?",
      outcome: "Marked hot after asking to order, and a payment link was sent in the chat.",
    },
  },
];

/** Blog articles that go deeper on each page; shown as "Read more" links. Slugs match blog-posts.ts. */
export const READ_MORE: Record<string, readonly string[]> = {
  "whatsapp-chatbot": ["what-is-a-whatsapp-chatbot", "instagram-auto-dm-reply-automatically", "case-study-customer-business-ai-replies"],
  "bulk-whatsapp-sender": ["send-bulk-whatsapp-messages-without-getting-blocked", "whatsapp-business-api-pricing-india"],
  "whatsapp-crm": ["what-is-a-lead-management-system", "hot-warm-cold-lead-scoring"],
  "telecaller-software": ["how-to-track-telecaller-performance"],
  "whatsapp-payments": ["whatsapp-business-api-pricing-india"],
  "social-media-ads": ["instagram-auto-dm-reply-automatically"],
  "real-estate": ["real-estate-lead-management-whatsapp", "hot-warm-cold-lead-scoring"],
  education: ["what-is-a-whatsapp-chatbot", "send-bulk-whatsapp-messages-without-getting-blocked"],
  "study-abroad": ["what-is-a-whatsapp-chatbot", "hot-warm-cold-lead-scoring"],
  healthcare: ["what-is-a-whatsapp-chatbot"],
  d2c: ["whatsapp-business-api-pricing-india", "instagram-auto-dm-reply-automatically"],
};

export const ALL_LANDINGS: readonly Landing[] = [...PRODUCT_PAGES, ...INDUSTRY_PAGES];

export function findLanding(list: readonly Landing[], slug: string): Landing | undefined {
  return list.find((l) => l.slug === slug);
}

/** A page that exists for this industry id (from INDUSTRIES), or undefined if it still lives only as an anchor. */
export function industryPagePath(id: string): string | undefined {
  return INDUSTRY_PAGES.find((p) => p.slug === id)?.path;
}
