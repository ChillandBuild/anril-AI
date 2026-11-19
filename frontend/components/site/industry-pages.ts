import type { FaqEntry } from "./schema";

// The eight industry pages (/industries/<slug>), word for word from
// "Anril – Complete website content and changes for team – 18 Nov 2026".
// Text in [brackets] inside a chat is a placeholder for the client's own details; the page shows it as one.

export type ChatMsg = {
  from: "them" | "us";
  /** Who is speaking in the "What X ask" cards (Parent, Student, Buyer ...). */
  who?: string;
  text: string;
  /** An attachment or payment link, shown as a chip instead of a text bubble. */
  kind?: "file" | "link";
};

export type LeadRow = { name: string; channel: string; note: string; score: "Hot" | "Warm" | "Cold"; time: string };

export type IndustryPage = {
  slug: string;
  path: string;
  /** Menu and card name. */
  label: string;
  /** Name in the breadcrumb structured data. */
  crumb: string;
  title: string;
  description: string;
  keywords: readonly string[];
  h1: string;
  line: string;
  heroChat: readonly ChatMsg[];
  heroTag: string;
  /** Describes the phone picture for screen readers and search (the hidden alt text). */
  heroAlt: string;
  quickAnswer: string;
  asksH: string;
  asksIntro: string;
  asks: readonly (readonly [ChatMsg, ChatMsg])[];
  steps: readonly (readonly [name: string, text: string])[];
  gets: readonly string[];
  shot: { caption: string; alt: string; rows: readonly LeadRow[] };
  faqs: readonly FaqEntry[];
  related: readonly { label: string; href: string; note: string }[];
};

/** The same last question on every industry page. */
export const COST_FAQ: FaqEntry = {
  q: "How much does it cost?",
  a: "Plans start from ₹999 a month (+GST). There is no free trial, but demos are free and you can take as many as you need. Our team will suggest the right plan in the demo.",
};

const PLANS = { label: "Plans", href: "/pricing", note: "Plans start from ₹999 a month (+GST)." } as const;
const BULK = { label: "Bulk WhatsApp sender", href: "/bulk-whatsapp-sender", note: "Official-API campaigns with approved templates." } as const;
const TELECALLER = { label: "Telecaller software", href: "/telecaller-software", note: "Record and score your team's calls, including Tamil calls." } as const;
const CRM = { label: "WhatsApp CRM", href: "/whatsapp-crm", note: "Every enquiry in one list, marked Hot, Warm or Cold." } as const;
const PAYMENTS = { label: "Payments and orders", href: "/whatsapp-payments", note: "Payment links, orders, stock and dispatch in one place." } as const;
const AGENT = { label: "WhatsApp AI agent", href: "/whatsapp-chatbot", note: "Replies to every enquiry in seconds, day and night." } as const;

function keywords(industry: string, ...extra: string[]): string[] {
  return [
    `whatsapp chatbot for ${industry}`,
    `ai chatbot for ${industry}`,
    `whatsapp ai agent for ${industry}`,
    `${industry} lead management`,
    `whatsapp automation for ${industry} Tamil Nadu`,
    ...extra,
  ];
}

export const INDUSTRY_PAGES: readonly IndustryPage[] = [
  {
    slug: "education",
    path: "/industries/education",
    label: "Education",
    crumb: "Education",
    title: "WhatsApp AI Agent for Schools & Colleges | Anril AI",
    description:
      "Anril AI replies to admission and course enquiries on WhatsApp, Instagram and Facebook in seconds, in Tamil, English or Tanglish, and sends serious students to your counsellors. From ₹999/month.",
    keywords: keywords("education", "whatsapp chatbot for schools", "whatsapp chatbot for colleges", "admission enquiry management"),
    h1: "WhatsApp AI agent for schools and colleges",
    line: "Anril replies to admission and course enquiries day and night, shares fees and brochures, and passes serious students and parents to your counsellors.",
    heroChat: [
      { from: "them", text: "Hi, B.Com admission open ah? Fees evlo?" },
      { from: "us", text: "Yes, admissions are open. Sharing the fee details and brochure now." },
      { from: "us", text: "Brochure.pdf", kind: "file" },
      { from: "them", text: "Campus visit Saturday possible?" },
      { from: "us", text: "Sure! Our counsellor will call you today to fix a time." },
    ],
    heroTag: "Marked HOT · sent to counsellor",
    heroAlt: "Anril WhatsApp AI agent replying to an admission enquiry in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for schools and colleges in India, made in Coimbatore. It replies to admission and fee enquiries on WhatsApp, Instagram and Facebook in seconds, in Tamil, English or Tanglish, marks each enquiry Hot, Warm or Cold, and passes serious students to counsellors. Plans start from ₹999 a month.",
    asksH: "What students and parents ask",
    asksIntro:
      "Most admission enquiries come in the evening, after school or office hours. Parents message several institutes at once and join the one that answers first.",
    asks: [
      [
        { from: "them", who: "Student", text: "What is the fee for B.Sc Computer Science?" },
        { from: "us", text: "Here is the fee structure and the brochure. Would you like to visit the campus?" },
      ],
      [
        { from: "them", who: "Parent", text: "Hostel facility irukka? Bus route enga varum?" },
        { from: "us", text: "Yes, here are the hostel details. Which area are you in? I'll check the bus route for you." },
      ],
      [
        { from: "them", who: "Student", text: "Last date for application?" },
        { from: "us", text: "Applications close on [date from your details]. Shall I share the application link?" },
      ],
    ],
    steps: [
      ["Answer", "Every enquiry gets a reply in seconds from your course list, fees, timings and documents, in Tamil, English or Tanglish. Voice notes too."],
      ["Mark", "Each enquiry is marked Hot, Warm or Cold based on what they ask. A parent asking for a campus visit is Hot."],
      ["Pass on", "Hot leads go to the right counsellor with the full chat on screen. Warm leads get a follow-up message if they go quiet."],
    ],
    gets: [
      "Replies 24/7 on WhatsApp, Instagram, Facebook and Telegram, all in one inbox",
      "Sends fee structure, brochures and photos in the chat",
      "Hot, Warm and Cold marks so counsellors call the right students first",
      "Bulk WhatsApp messages for admission dates, results and events, on the official WhatsApp API",
      "Leads from your Facebook and Instagram lead forms come into the same list",
    ],
    shot: {
      caption: "Every admission enquiry in one list, with the hottest students at the top.",
      alt: "Anril dashboard lead list for a college, with admission enquiries marked Hot, Warm and Cold",
      rows: [
        { name: "Kavya Raman", channel: "WhatsApp", note: "Campus visit on Saturday", score: "Hot", time: "2 min" },
        { name: "Suresh (parent)", channel: "Instagram", note: "Hostel and bus route", score: "Hot", time: "11 min" },
        { name: "Nithin Prakash", channel: "WhatsApp", note: "B.Sc CS fee structure", score: "Warm", time: "34 min" },
        { name: "Harini S", channel: "Facebook", note: "Last date for application", score: "Warm", time: "1 h" },
        { name: "Arjun M", channel: "WhatsApp", note: "Asked about courses", score: "Cold", time: "3 h" },
      ],
    },
    faqs: [
      { q: "Does it reply in Tamil?", a: "Yes. Tanglish by default, and Tamil, English or any other language, based on how the student or parent writes. It understands voice notes too." },
      { q: "Can it send our brochure and fee details?", a: "Yes. It sends your brochure, fee details and photos right in the chat." },
      { q: "What if a parent asks something the AI doesn't know?", a: "It does not guess. It passes the chat to your team with the full history." },
      { q: "Can we send admission updates to all past enquiries?", a: "Yes. Anril Reach sends bulk WhatsApp messages through the official WhatsApp API, to people who agreed to hear from you." },
      COST_FAQ,
    ],
    related: [
      { label: "Study abroad consultancies", href: "/industries/study-abroad", note: "Country, course and budget collected before the first call." },
      BULK,
      PLANS,
    ],
  },
  {
    slug: "study-abroad",
    path: "/industries/study-abroad",
    label: "Study abroad",
    crumb: "Study Abroad",
    title: "WhatsApp AI Agent for Study Abroad Consultancies | Anril AI",
    description:
      "Reply to every study-abroad enquiry in seconds, mark serious students Hot, Warm or Cold, and pass them to your counsellors. WhatsApp, Instagram and Facebook in one place. From ₹999/month.",
    keywords: keywords("study abroad consultants", "whatsapp chatbot for study abroad consultancy", "overseas education lead management"),
    h1: "WhatsApp AI agent for study-abroad consultancies",
    line: "Anril replies to students' and parents' enquiries at any hour, collects country, course and budget, and passes serious students to your counsellors with the whole chat.",
    heroChat: [
      { from: "them", text: "I want to do MS in Canada. IELTS 6.5 podhuma?" },
      { from: "us", text: "6.5 works for many courses. Which intake are you planning, and what is your budget?" },
      { from: "them", text: "Sept intake, around 25 lakhs." },
      { from: "us", text: "Thanks! Our counsellor will call you today with options." },
    ],
    heroTag: "Marked HOT · sent to counsellor",
    heroAlt: "Anril WhatsApp AI agent replying to a study-abroad enquiry in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for study-abroad consultancies in India. It replies to student enquiries at any hour, collects country, course, intake and budget, marks each student Hot, Warm or Cold, and sends serious students to counsellors with the full chat. Plans start from ₹999 a month.",
    asksH: "What students ask",
    asksIntro:
      "Students compare many consultancies on Instagram and WhatsApp, often late at night. The first useful reply wins the counselling session.",
    asks: [
      [
        { from: "them", who: "Student", text: "Which countries have low fees?" },
        { from: "us", text: "Here are the countries we help with. Which course are you interested in?" },
      ],
      [
        { from: "them", who: "Parent", text: "What documents are needed?" },
        { from: "us", text: "Here is the document list. Shall I book a free counselling call?" },
      ],
      [
        { from: "them", who: "Student", text: "Do you help with education loan?" },
        { from: "us", text: "Our counsellor will explain the loan options. What is a good time to call you?" },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds from your country list, courses, intakes and document list."],
      ["Collect", "Asks one question at a time: country, course, intake, budget, city."],
      ["Pass on", "Serious students are marked Hot and sent to a counsellor with every detail already collected."],
    ],
    gets: [
      "One inbox for WhatsApp, Instagram, Facebook and Telegram",
      "Student details collected in the chat, so counsellors don't ask again",
      "Hot, Warm and Cold marks on every enquiry",
      "Follow-up message when a student goes quiet",
      "Call scoring for your counsellors' calls, including Tamil calls (Telecaller software)",
    ],
    shot: {
      caption: "Country, course and budget for every student, before the first call.",
      alt: "Anril dashboard lead list for a study-abroad consultancy, with country, course and budget for each student",
      rows: [
        { name: "Rahul Venkat", channel: "WhatsApp", note: "MS Canada · Sept · ₹25 L", score: "Hot", time: "4 min" },
        { name: "Sneha Iyer", channel: "Instagram", note: "Nursing UK · Jan intake", score: "Hot", time: "18 min" },
        { name: "Mohammed Asif", channel: "WhatsApp", note: "MBA Germany · documents", score: "Warm", time: "42 min" },
        { name: "Deepa K", channel: "Facebook", note: "Low-fee countries", score: "Warm", time: "2 h" },
        { name: "Vignesh R", channel: "Telegram", note: "Just browsing", score: "Cold", time: "5 h" },
      ],
    },
    faqs: [
      { q: "Can it handle Instagram DMs from our ads?", a: "Yes. Instagram, Facebook and WhatsApp enquiries all come into one list and get the same quick reply." },
      { q: "Will it give wrong visa information?", a: "It answers only from the information you give us. Questions it can't answer go to your counsellor." },
      { q: "Can our team take over a chat?", a: "Yes, any time. The full chat stays on screen." },
      { q: "Can we see which counsellor converts best?", a: "Yes. The telecaller software scores each counsellor's calls, so you know who converts and who needs help." },
      COST_FAQ,
    ],
    related: [
      { label: "Education", href: "/industries/education", note: "Admission and fee enquiries answered day and night." },
      TELECALLER,
      PLANS,
    ],
  },
  {
    slug: "real-estate",
    path: "/industries/real-estate",
    label: "Real estate",
    crumb: "Real Estate",
    title: "WhatsApp AI Agent for Real Estate | Anril AI",
    description:
      "Reply to every property enquiry from ads in seconds, ask budget and location, collect site-visit times and send serious buyers to your sales team. From ₹999/month.",
    keywords: keywords("real estate", "whatsapp chatbot for builders", "property enquiry management"),
    h1: "WhatsApp AI agent for real estate",
    line: "Ad leads go cold in minutes. Anril replies at once, shares project details, asks budget and location, and sends only serious buyers to your sales team.",
    heroChat: [
      { from: "them", text: "2BHK price evlo? Location enga?" },
      { from: "us", text: "Here are the 2BHK details, floor plan and location map. What is your budget?" },
      { from: "them", text: "Around 60 lakhs. Sunday visit pannalama?" },
      { from: "us", text: "Sure! Our sales team will call you to confirm the site visit." },
    ],
    heroTag: "Marked HOT · sent to sales",
    heroAlt: "Anril WhatsApp AI agent replying to a 2BHK property enquiry in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for builders and real estate agents in India. It replies to property enquiries from ads in seconds, shares photos and floor plans, asks budget and location, and sends buyers who want a site visit to the sales team. Plans start from ₹999 a month.",
    asksH: "What buyers ask",
    asksIntro:
      "Most property enquiries come from Facebook and Instagram ads, at night and on weekends. A buyer who waits an hour has already called two other builders.",
    asks: [
      [
        { from: "them", who: "Buyer", text: "Is it DTCP approved?" },
        { from: "us", text: "Here are the approval details for the project. Would you like to see the plot layout?" },
      ],
      [
        { from: "them", who: "Buyer", text: "Loan facility available?" },
        { from: "us", text: "Our team will explain the loan options. What is a good time to call?" },
      ],
      [
        { from: "them", who: "Buyer", text: "Send photos of the flat." },
        { from: "us", text: "Here are the photos and the floor plan. Shall I arrange a site visit?" },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with project details, photos, floor plans and location from your information."],
      ["Qualify", "Asks budget, size and preferred location, and marks each buyer Hot, Warm or Cold."],
      ["Pass on", "Buyers asking for a site visit go to your sales team with the full chat and their preferred day."],
    ],
    gets: [
      "Instant replies to every ad enquiry, even at 11 PM",
      "Sends photos, floor plans and brochures in the chat",
      "Leads from Facebook and Instagram lead forms in the same list",
      "Hot, Warm and Cold marks so your team calls the right buyers first",
      "Bulk WhatsApp messages for new launches and offers, on the official WhatsApp API",
    ],
    shot: {
      caption: "Every buyer with budget and location, hottest at the top.",
      alt: "Anril dashboard lead list for a builder, with each buyer's budget and location",
      rows: [
        { name: "Senthil Kumar", channel: "WhatsApp", note: "2BHK · ₹60 L · Sunday visit", score: "Hot", time: "3 min" },
        { name: "Anitha J", channel: "Facebook", note: "3BHK · Saravanampatti", score: "Hot", time: "15 min" },
        { name: "Ravi Shankar", channel: "Instagram", note: "Plot · DTCP approval", score: "Warm", time: "48 min" },
        { name: "Lakshmi N", channel: "WhatsApp", note: "Loan options", score: "Warm", time: "2 h" },
        { name: "Gopal V", channel: "Facebook", note: "Asked for photos", score: "Cold", time: "6 h" },
      ],
    },
    faqs: [
      { q: "Can it reply to leads from our Facebook ads?", a: "Yes. Click-to-WhatsApp ads, Instagram DMs and lead forms all come into one list and get an instant reply." },
      { q: "Can it send brochures and floor plans?", a: "Yes. It sends photos, brochures and price lists in the chat." },
      { q: "Will it promise prices or discounts?", a: "No. It answers only from the details you give us. Anything else goes to your sales team." },
      { q: "Can we track our sales team's calls?", a: "Yes. The telecaller software records and scores your team's calls, including Tamil calls." },
      COST_FAQ,
    ],
    related: [TELECALLER, BULK, PLANS],
  },
  {
    slug: "healthcare",
    path: "/industries/healthcare",
    label: "Healthcare",
    crumb: "Healthcare",
    title: "WhatsApp AI Agent for Hospitals & Clinics | Anril AI",
    description:
      "Answer patient questions about timings, doctors and fees on WhatsApp in seconds, collect appointment requests and send them to your front desk. From ₹999/month.",
    keywords: keywords("hospitals and clinics", "whatsapp chatbot for clinics", "healthcare lead management"),
    h1: "WhatsApp AI agent for hospitals and clinics",
    line: "Anril answers patient questions about doctors, timings and services, and sends appointment requests to your front desk. It never gives medical advice.",
    heroChat: [
      { from: "them", text: "Dr. Kumar evening la irupparaa?" },
      { from: "us", text: "Dr. Kumar is available from 5 PM to 8 PM, Monday to Saturday. Would you like to book an appointment?" },
      { from: "them", text: "Yes, tomorrow evening." },
      { from: "us", text: "Thank you. Our front desk will call you to confirm the time." },
    ],
    heroTag: "Appointment request · sent to front desk",
    heroAlt: "Anril WhatsApp AI agent answering a patient's question about a doctor's timings in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for hospitals and clinics in India. It answers patient questions about doctors, timings and fees in seconds, collects appointment requests for the front desk, and hands every medical question to a person. Plans start from ₹999 a month.",
    asksH: "What patients ask",
    asksIntro:
      "Patients message for timings, fees and appointments, often after the clinic closes. Your front desk is busy with the people in front of them.",
    asks: [
      [
        { from: "them", who: "Patient", text: "Consultation fee evlo?" },
        { from: "us", text: "The consultation fee is [from your details]. Shall I take your appointment request?" },
      ],
      [
        { from: "them", who: "Patient", text: "Is there parking?" },
        { from: "us", text: "Yes. Here is the location and parking details." },
      ],
      [
        { from: "them", who: "Patient", text: "Do you do blood tests on Sunday?" },
        { from: "us", text: "Here are our lab timings." },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds to common questions: doctors, timings, fees, location, services."],
      ["Collect", "Takes the patient's name, preferred doctor and time for an appointment request."],
      ["Pass on", "Your front desk confirms. Medical questions and anything urgent go straight to your team."],
    ],
    gets: [
      "Replies 24/7 in Tamil, English or Tanglish, including voice notes",
      "Appointment requests collected in the chat",
      "Medical questions always handed to a person, never answered by the AI",
      "One inbox for WhatsApp, Instagram and Facebook",
      "Bulk WhatsApp messages for health camps and reminders, to patients who agreed to hear from you",
    ],
    shot: {
      caption: "Every appointment request in one list for your front desk.",
      alt: "Anril dashboard list of patient appointment requests for a clinic front desk",
      rows: [
        { name: "Meena Sundar", channel: "WhatsApp", note: "Dr. Kumar · tomorrow evening", score: "Hot", time: "5 min" },
        { name: "Prakash R", channel: "WhatsApp", note: "Physio appointment · Monday", score: "Hot", time: "22 min" },
        { name: "Fathima B", channel: "Instagram", note: "Consultation fee", score: "Warm", time: "1 h" },
        { name: "Sathish K", channel: "Facebook", note: "Sunday lab timings", score: "Warm", time: "2 h" },
        { name: "Rekha P", channel: "WhatsApp", note: "Parking details", score: "Cold", time: "4 h" },
      ],
    },
    faqs: [
      { q: "Will the AI give medical advice?", a: "No. It answers only general questions like timings and fees. Medical questions go to your team." },
      { q: "Is patient data safe?", a: "We use the official WhatsApp Business API, and chats stay in your own dashboard. See our privacy policy." },
      { q: "Does it book the appointment itself?", a: "It collects the request and preferred time. Your front desk confirms it." },
      { q: "Can it reply in Tamil?", a: "Yes, in Tamil, English, Tanglish or the language the patient uses, including voice notes." },
      COST_FAQ,
    ],
    related: [AGENT, BULK, PLANS],
  },
  {
    slug: "automotive",
    path: "/industries/automotive",
    label: "Automotive",
    crumb: "Automotive",
    title: "WhatsApp AI Agent for Car & Bike Dealers | Anril AI",
    description:
      "Reply to every price and test-drive enquiry on WhatsApp in seconds, collect model and budget, and send hot buyers to your sales team. From ₹999/month.",
    keywords: keywords("car dealers", "whatsapp chatbot for bike dealers", "automotive lead management", "whatsapp automation for automotive Tamil Nadu"),
    h1: "WhatsApp AI agent for car and bike dealers",
    line: "Anril replies to every price, EMI and test-drive enquiry at once, collects the model and budget, and sends hot buyers to your sales executives.",
    heroChat: [
      { from: "them", text: "What is the on-road price for the automatic?" },
      { from: "us", text: "I can share the on-road price for your city. Which city are you in? Would you also like to book a test drive?" },
      { from: "them", text: "Coimbatore. Test drive Saturday." },
      { from: "us", text: "Our sales executive will call you to confirm Saturday." },
    ],
    heroTag: "Marked HOT · sent to sales",
    heroAlt: "Anril WhatsApp AI agent replying to an on-road price and test-drive enquiry",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for car and bike dealers in India. It replies to price, EMI and test-drive enquiries in seconds, collects model, budget and city, and sends hot buyers to sales executives. Plans start from ₹999 a month.",
    asksH: "What buyers ask",
    asksIntro:
      "Buyers ask three or four dealers the same question. The dealer who replies first with a clear answer gets the showroom visit.",
    asks: [
      [
        { from: "them", who: "Buyer", text: "EMI evlo varum?" },
        { from: "us", text: "Our team will share the EMI options. Which model and down payment are you looking at?" },
      ],
      [
        { from: "them", who: "Buyer", text: "Which colours are available?" },
        { from: "us", text: "Here are the colours and photos for this model." },
      ],
      [
        { from: "them", who: "Customer", text: "I want to book a service." },
        { from: "us", text: "Sure. Please share your vehicle number and preferred day, and our service team will confirm." },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with models, colours, photos and price details from your information."],
      ["Qualify", "Asks model, budget, city and when they plan to buy. Marks each buyer Hot, Warm or Cold."],
      ["Pass on", "Test-drive and booking requests go to your sales executive with the full chat."],
    ],
    gets: [
      "Instant replies to every ad and Instagram enquiry",
      "Sends model photos and price lists in the chat",
      "Hot, Warm and Cold marks on every buyer",
      "Bulk WhatsApp messages for offers and service reminders, on the official WhatsApp API",
      "Call scoring for your sales executives (Telecaller software)",
    ],
    shot: {
      caption: "Every buyer with model and budget, ready for your sales team.",
      alt: "Anril dashboard lead list for a car dealer, with each buyer's model and budget",
      rows: [
        { name: "Karthik Vel", channel: "WhatsApp", note: "Automatic · test drive Saturday", score: "Hot", time: "2 min" },
        { name: "Divya Mohan", channel: "Instagram", note: "Scooter · EMI · ₹20k down", score: "Hot", time: "19 min" },
        { name: "Balaji S", channel: "Facebook", note: "SUV colours", score: "Warm", time: "55 min" },
        { name: "Joseph A", channel: "WhatsApp", note: "Service booking · Tuesday", score: "Warm", time: "2 h" },
        { name: "Naveen T", channel: "Instagram", note: "Price list", score: "Cold", time: "7 h" },
      ],
    },
    faqs: [
      { q: "Can it share on-road prices?", a: "Yes, from the price details you give us. When prices change, update them in the dashboard and the AI uses them at once." },
      { q: "Can it handle service bookings too?", a: "It collects the vehicle number and preferred day, and your service team confirms." },
      { q: "Can we send offers to old customers?", a: "Yes. Anril Reach sends bulk WhatsApp messages to customers who agreed to hear from you." },
      { q: "Can we track our sales calls?", a: "Yes. The telecaller software records and scores every sales call, including Tamil calls." },
      COST_FAQ,
    ],
    related: [TELECALLER, BULK, PLANS],
  },
  {
    slug: "manufacturing",
    path: "/industries/manufacturing",
    label: "Manufacturing",
    crumb: "Manufacturing",
    title: "WhatsApp AI Agent for Manufacturers & B2B Suppliers | Anril AI",
    description:
      "Reply to every buyer enquiry in seconds, collect product, quantity and location, and pass qualified B2B leads to your sales team. IndiaMART and JustDial leads too. From ₹999/month.",
    keywords: keywords("manufacturers", "whatsapp chatbot for b2b", "b2b lead management", "indiamart lead management", "whatsapp automation for manufacturing Tamil Nadu"),
    h1: "WhatsApp AI agent for manufacturers and suppliers",
    line: "Anril replies to every buyer enquiry, collects the product, quantity and delivery location, and passes qualified leads to your sales team, so no big order is missed.",
    heroChat: [
      { from: "them", text: "Can you quote for 500 units, delivered next month?" },
      { from: "us", text: "Yes, we can quote for 500 units. Please share the specification and delivery location, and our team will send the quote." },
      { from: "them", text: "Specification.pdf", kind: "file" },
    ],
    heroTag: "Marked HOT · sent to sales",
    heroAlt: "Anril WhatsApp AI agent replying to a B2B quote request for 500 units",
    // IndiaMART and JustDial intake is live, but the first contact to those leads is an approved WhatsApp
    // welcome message, so the copy says that rather than promising an AI reply.
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for manufacturers and B2B suppliers in India. It replies to buyer enquiries on WhatsApp in seconds, brings IndiaMART and JustDial leads into the same list, collects product, quantity and delivery location, and passes qualified leads to the sales team. Plans start from ₹999 a month.",
    asksH: "What buyers ask",
    asksIntro:
      "B2B buyers send the same enquiry to many suppliers on IndiaMART, JustDial and WhatsApp. The supplier who replies first and asks the right questions gets the quote request.",
    asks: [
      [
        { from: "them", who: "Buyer", text: "Minimum order quantity?" },
        { from: "us", text: "Our minimum order is [from your details]. What quantity do you need?" },
      ],
      [
        { from: "them", who: "Buyer", text: "Samples kidaikkuma?" },
        { from: "us", text: "Our team will confirm samples. Which product and where should we send it?" },
      ],
      [
        { from: "them", who: "Buyer", text: "Delivery time to Bangalore?" },
        { from: "us", text: "Usually [from your details]. Shall I ask our team for an exact date with the quote?" },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds from your product list, specifications and terms."],
      ["Collect", "Asks product, quantity, delivery location and timeline, one question at a time."],
      ["Pass on", "Qualified buyers go to your sales team with the full requirement, ready to quote."],
    ],
    gets: [
      "IndiaMART, JustDial and website enquiries in the same list as WhatsApp",
      "Instant first reply on WhatsApp, and a welcome message to every new IndiaMART or JustDial lead",
      "Requirement details collected before your team calls",
      "Hot, Warm and Cold marks on every buyer",
      "Product catalogue, price lists and GST invoices (Anril Commerce)",
    ],
    shot: {
      caption: "Every buyer requirement in one list, from every lead source.",
      alt: "Anril dashboard lead list for a manufacturer, with each buyer's product, quantity and lead source",
      rows: [
        { name: "Sri Balaji Traders", channel: "WhatsApp", note: "500 units · next month", score: "Hot", time: "6 min" },
        { name: "Ramesh Industries", channel: "IndiaMART", note: "Quote · 2,000 pcs · Chennai", score: "Hot", time: "25 min" },
        { name: "Vasanth Enterprises", channel: "JustDial", note: "Samples · Bangalore", score: "Warm", time: "1 h" },
        { name: "Kumaran Agencies", channel: "Website", note: "Minimum order quantity", score: "Warm", time: "3 h" },
        { name: "Arul Stores", channel: "WhatsApp", note: "Catalogue", score: "Cold", time: "8 h" },
      ],
    },
    faqs: [
      { q: "Can it reply to IndiaMART and JustDial leads?", a: "Yes. IndiaMART and JustDial leads come into the same list as your WhatsApp enquiries, and each new lead can get an approved WhatsApp welcome message at once." },
      { q: "Will it quote prices on its own?", a: "Only prices you have given it. Custom quotes are passed to your sales team." },
      { q: "Does it work for B2B?", a: "Yes. It collects the requirement, scores the lead, and your sales team follows up from one dashboard." },
      { q: "Can we send our catalogue?", a: "Yes. It sends your catalogue, photos and price lists in the chat." },
      COST_FAQ,
    ],
    related: [CRM, PAYMENTS, PLANS],
  },
  {
    slug: "financial-services",
    path: "/industries/financial-services",
    label: "Financial services",
    crumb: "Financial Services",
    title: "WhatsApp AI Agent for Loans & Insurance | Anril AI",
    description:
      "Answer common loan and insurance questions in seconds, collect basic details, mark leads Hot, Warm or Cold, and send serious ones to your advisors. From ₹999/month.",
    keywords: keywords("financial services", "whatsapp chatbot for loans", "whatsapp chatbot for insurance", "loan lead management"),
    h1: "WhatsApp AI agent for loans and insurance",
    line: "Anril answers common questions about eligibility, documents and plans, collects basic details, and sends serious leads to your advisors.",
    heroChat: [
      { from: "them", text: "Am I eligible for a business loan? Please call me." },
      { from: "us", text: "I can help with that. What kind of business do you run, and how long has it been trading? A loan advisor will then call you." },
      { from: "them", text: "Textile shop, 4 years." },
    ],
    heroTag: "Marked HOT · sent to advisor",
    heroAlt: "Anril WhatsApp AI agent replying to a business loan enquiry",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for loan and insurance businesses in India. It answers common questions about documents and products, collects basic details, marks each lead Hot, Warm or Cold, and sends serious leads to advisors. Plans start from ₹999 a month.",
    asksH: "What customers ask",
    asksIntro:
      "Loan and insurance enquiries come from ads and referrals at all hours. Customers want a quick, clear answer before they share their details.",
    asks: [
      [
        { from: "them", who: "Customer", text: "What documents are needed for a home loan?" },
        { from: "us", text: "Here is the document list. Shall I ask an advisor to call you?" },
      ],
      [
        { from: "them", who: "Customer", text: "Term insurance plans evlo?" },
        { from: "us", text: "Our advisor will explain the plans for your age and cover. What is a good time to call?" },
      ],
      [
        { from: "them", who: "Customer", text: "What is the interest rate?" },
        { from: "us", text: "Rates depend on your profile. Our advisor will share the exact rate. Can I take your name and city?" },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds to common questions from your information: documents, products, process."],
      ["Collect", "Takes name, city and what they need, one question at a time."],
      ["Pass on", "Serious leads go to an advisor. Rates and eligibility are always confirmed by your team, not the AI."],
    ],
    gets: [
      "Instant replies on WhatsApp, Instagram and Facebook",
      "Basic details collected before your advisor calls",
      "Hot, Warm and Cold marks on every lead",
      "Follow-up message when a lead goes quiet",
      "Call scoring for your advisors' calls, including Tamil calls (Telecaller software)",
    ],
    shot: {
      caption: "Every lead with what they need, ready for your advisors.",
      alt: "Anril dashboard lead list for a loan and insurance business, with what each lead needs",
      rows: [
        { name: "Murugan S", channel: "WhatsApp", note: "Business loan · textile shop", score: "Hot", time: "3 min" },
        { name: "Priya Natarajan", channel: "Facebook", note: "Home loan · documents", score: "Hot", time: "27 min" },
        { name: "Imran K", channel: "Instagram", note: "Term insurance · age 34", score: "Warm", time: "1 h" },
        { name: "Saranya D", channel: "WhatsApp", note: "Interest rate", score: "Warm", time: "3 h" },
        { name: "Elango P", channel: "Facebook", note: "General question", score: "Cold", time: "9 h" },
      ],
    },
    faqs: [
      { q: "Will the AI tell customers their interest rate?", a: "No. It shares only what you give it. Rates and eligibility are confirmed by your advisors." },
      { q: "Is customer data safe?", a: "We use the official WhatsApp Business API, and chats stay in your own dashboard. See our privacy policy." },
      { q: "Can it reply in Tamil?", a: "Yes, in Tamil, English, Tanglish or the customer's language, including voice notes." },
      { q: "Can we check our advisors' calls?", a: "Yes. The telecaller software records and scores every call, so you know who converts." },
      COST_FAQ,
    ],
    related: [TELECALLER, CRM, PLANS],
  },
  {
    slug: "d2c",
    path: "/industries/d2c",
    label: "D2C brands",
    crumb: "D2C Brands",
    title: "WhatsApp AI Agent for D2C Brands & Online Sellers | Anril AI",
    description:
      "Reply to every price, size and delivery question in seconds, send Razorpay payment links in the chat, and track orders and stock in one place. From ₹999/month.",
    keywords: keywords("d2c brands", "whatsapp chatbot for online sellers", "whatsapp chatbot for ecommerce", "whatsapp payment link"),
    h1: "WhatsApp AI agent for D2C brands and online sellers",
    line: "Anril replies to every 'price?', 'size irukka?' and 'delivery?' message at once, sends a payment link in the chat, and updates your stock after the order.",
    heroChat: [
      { from: "them", text: "Price evlo? M size irukka?" },
      { from: "us", text: "₹[price from your list]. Yes, M size is in stock. Shall I send the payment link?" },
      { from: "them", text: "Yes." },
      { from: "us", text: "Payment link", kind: "link" },
    ],
    heroTag: "Paid · order created",
    heroAlt: "Anril WhatsApp AI agent answering a size and price question and sending a payment link",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for D2C brands and online sellers in India. It replies to price, size and delivery questions in seconds, sends Razorpay payment links in the chat, and tracks orders, stock and dispatch in one place. Plans start from ₹999 a month.",
    asksH: "What customers ask",
    asksIntro:
      "Customers who see your Instagram post message at once. If nobody replies in a few minutes, they scroll to the next brand.",
    asks: [
      [
        { from: "them", who: "Customer", text: "Delivery to Chennai evlo naal?" },
        { from: "us", text: "Usually [from your details]. Would you like to order now?" },
      ],
      [
        { from: "them", who: "Customer", text: "Send more photos of this colour." },
        { from: "us", text: "Here are more photos of this colour." },
      ],
      [
        { from: "them", who: "Customer", text: "Where is my order?" },
        { from: "us", text: "Your order is dispatched. Here is the latest status." },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with price, sizes, colours, photos and delivery details from your catalogue."],
      ["Sell", "Sends a Razorpay payment link in the chat and shows paid, pending or failed."],
      ["Track", "The order is created, stock updates automatically, and you track dispatch and delivery."],
    ],
    gets: [
      "Replies 24/7 on WhatsApp, Instagram and Facebook",
      "Payment links in the chat (UPI, cards, net banking through Razorpay)",
      "Orders, GST invoices, stock with low-stock alerts, and dispatch status (Anril Commerce)",
      "Bulk WhatsApp messages for new launches and sales, on the official WhatsApp API",
      "Hot, Warm and Cold marks so you follow up the right customers",
    ],
    shot: {
      caption: "From enquiry to paid order, in one place.",
      alt: "Anril dashboard lead list for a D2C brand, with paid orders and open enquiries",
      rows: [
        { name: "Aishwarya R", channel: "Instagram", note: "Kurta · M · paid", score: "Hot", time: "1 min" },
        { name: "Nandhini P", channel: "WhatsApp", note: "Payment link sent", score: "Hot", time: "12 min" },
        { name: "Swetha K", channel: "Instagram", note: "More photos · blue", score: "Warm", time: "40 min" },
        { name: "Janani V", channel: "Facebook", note: "Delivery to Chennai", score: "Warm", time: "2 h" },
        { name: "Keerthi S", channel: "WhatsApp", note: "Price only", score: "Cold", time: "5 h" },
      ],
    },
    faqs: [
      { q: "Can customers pay inside the chat?", a: "Yes. The AI sends a Razorpay payment link, and you see whether it is paid, pending or failed." },
      { q: "Does stock update by itself?", a: "Yes. Stock updates after each order, and you get low-stock alerts." },
      // The doc said "the chat goes to your team"; the backend instead asks the customer to type (webhook.py _MEDIA_ACK_TEXT).
      { q: "Can it understand photos customers send?", a: "Not yet. If a customer sends a photo, Anril asks them to type their question, and the photo stays in the chat for your team to see." },
      { q: "Does it work with Shopify or my website?", a: "Our team will check this for your setup in the demo." },
      COST_FAQ,
    ],
    related: [PAYMENTS, BULK, PLANS],
  },
];

export function findIndustryPage(slug: string): IndustryPage | undefined {
  return INDUSTRY_PAGES.find((p) => p.slug === slug);
}
