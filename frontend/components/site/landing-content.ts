import type { FaqEntry } from "./schema";

// Copy for the product pages (/whatsapp-chatbot ...). The industry pages live in industry-pages.ts.
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
};

export const PRODUCT_PAGES: readonly Landing[] = [
  {
    slug: "whatsapp-chatbot",
    path: "/whatsapp-chatbot",
    kicker: "Engage",
    label: "WhatsApp AI agent",
    title: "WhatsApp AI Agent in Tanglish for Business | Anril AI",
    description:
      "Anril's WhatsApp AI agent replies to every enquiry in seconds, day and night, in Tanglish or any language, and scores leads Hot, Warm or Cold. From ₹999.",
    h1: "WhatsApp AI agent that replies to every enquiry",
    opening:
      "Anril's WhatsApp AI agent answers customer enquiries on WhatsApp, Instagram and Facebook in seconds, using your own business information. It replies in Tanglish by default, understands voice notes, scores each lead Hot, Warm or Cold, and hands over to your team when needed.",
    sections: [
      {
        h: "What can Anril's AI agent answer?",
        p: [
          "It answers from the information you give it about your business: your services, prices, timings, locations, policies and the questions your customers ask most. You keep that information in a knowledge base, and the AI agent uses it for every reply.",
          "The AI agent can also send photos and price lists in the chat. It cannot read images that customers send to it.",
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
          "Hot leads reach your team first, and the AI agent follows up with leads automatically so that a warm enquiry does not go quiet.",
        ],
      },
      {
        h: "What happens when a customer wants to talk to a person?",
        p: [
          "The chat is handed over to your team with everything that was said so far, so nobody has to ask the customer to repeat themselves. Your team then continues the conversation from the same place. If a customer asks whether they are talking to an AI, the AI agent says that it is an AI assistant.",
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
      { q: "Does the AI agent work at night and on holidays?", a: "Yes. It replies to every enquiry as soon as it arrives." },
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
    title: "Bulk WhatsApp Sender (Official API) | Anril AI",
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
          "Anril's AI agent replies instantly and scores the lead, so a customer who answers a campaign is not left waiting. Hot leads reach your team first. Campaigns, replies and leads sit in the same platform, so you can see what each campaign brought in.",
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
        a: "Anril's AI agent replies instantly and scores the lead, so hot leads reach your team first.",
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
      "Every WhatsApp, Instagram and Facebook enquiry in one list, scored Hot, Warm or Cold, with follow-ups and handover. Know who to call first. From ₹999.",
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
      "Record every sales call, understand Tamil conversations and measure each telecaller's performance. Unlimited calls and recording.",
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
      { q: "How is CallIQ billed?", a: "CallIQ is priced by team size. Message us on WhatsApp for a quote." },
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
    title: "Done-for-You Social Media & Ads with Leads | Anril Attract",
    description:
      "We run your Instagram and Facebook posts plus Meta and Google ads, and every lead goes straight into Anril's AI chat.",
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

/** Blog articles that go deeper on each page; shown as "Read more" links. Slugs match blog-posts.ts. */
export const READ_MORE: Record<string, readonly string[]> = {
  "whatsapp-chatbot": ["what-is-a-whatsapp-chatbot", "how-to-choose-a-whatsapp-business-tool", "case-study-customer-business-ai-replies"],
  "bulk-whatsapp-sender": ["send-bulk-whatsapp-messages-without-getting-blocked", "whatsapp-business-api-pricing-india"],
  "whatsapp-crm": ["what-is-a-lead-management-system", "hot-warm-cold-lead-scoring"],
  "telecaller-software": ["how-to-track-telecaller-performance"],
  "whatsapp-payments": ["whatsapp-business-api-pricing-india"],
  "social-media-ads": ["instagram-auto-dm-reply-automatically"],
};

/** Product pages. The industry pages have their own layout and data (industry-pages.ts). */
export const ALL_LANDINGS: readonly Landing[] = PRODUCT_PAGES;

export function findLanding(list: readonly Landing[], slug: string): Landing | undefined {
  return list.find((l) => l.slug === slug);
}
