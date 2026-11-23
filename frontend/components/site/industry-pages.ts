import type { FaqEntry } from "./schema";

// The 20 industry pages (/industries/<slug>), word for word from
// "Anril – Complete website content and changes for team – 18 Nov 2026" (the first eight) and the
// "Website changes for the team – 22 Nov 2026" work order (the twelve after them).
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

/** Other industry pages, for the "Related" links. */
const IND = {
  education: { label: "Education", href: "/industries/education", note: "Admission and fee enquiries answered day and night." },
  realEstate: { label: "Real estate", href: "/industries/real-estate", note: "Site visits booked, buyers marked Hot, Warm or Cold." },
  healthcare: { label: "Healthcare", href: "/industries/healthcare", note: "Appointment requests sent to your front desk." },
  d2c: { label: "D2C brands", href: "/industries/d2c", note: "Orders, payment links and dispatch from the chat." },
  retail: { label: "Retail shops", href: "/industries/retail", note: "Price, stock and colour questions answered in seconds." },
  salons: { label: "Salons and beauty", href: "/industries/salons-beauty", note: "Service questions answered, appointment requests collected." },
  travel: { label: "Travel and tours", href: "/industries/travel-tours", note: "Package enquiries with dates, people and budget." },
  hotels: { label: "Hotels and resorts", href: "/industries/hotels-resorts", note: "Booking requests sent to your front desk." },
  restaurants: { label: "Restaurants", href: "/industries/restaurants", note: "Menu shared, party and catering enquiries collected." },
  events: { label: "Events and weddings", href: "/industries/events-weddings", note: "Date, venue and budget collected for every client." },
  finance: { label: "Financial services", href: "/industries/financial-services", note: "Loan and insurance leads sent to your advisors." },
} as const;

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
      "Anril AI is a WhatsApp AI agent for schools and colleges in India. It replies to admission and fee enquiries on WhatsApp, Instagram and Facebook in seconds, in Tamil, English or Tanglish, marks each enquiry Hot, Warm or Cold, and passes serious students to counsellors. Plans start from ₹999 a month.",
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
  {
    slug: "coaching",
    path: "/industries/coaching",
    label: "Coaching and training institutes",
    crumb: "Coaching & Training",
    title: "WhatsApp AI Agent for Coaching & Training Institutes | Anril AI",
    description:
      "Reply to every course, batch and fee enquiry in seconds, send your brochure, mark students Hot, Warm or Cold and pass serious ones to your counsellors. From ₹999/month.",
    keywords: ["whatsapp chatbot for coaching centres", "ai chatbot for coaching centres", "whatsapp ai agent for coaching centres", "coaching centres lead management", "whatsapp automation for coaching centres Tamil Nadu", "coaching centres enquiry management software"],
    h1: "WhatsApp AI agent for coaching and training institutes",
    line: "Anril replies to every course, batch and fee enquiry at once, sends your brochure and timetable, and passes serious students and parents to your counsellors.",
    heroChat: [
      { from: "them", text: "NEET coaching weekend batch irukka? Fees evlo?" },
      { from: "us", text: "Yes, we have a weekend batch. Sharing the fee details and brochure now." },
      { from: "us", text: "Brochure.pdf", kind: "file" },
      { from: "them", text: "Demo class attend pannalama?" },
      { from: "us", text: "Sure! Our counsellor will call you today to fix a demo class." },
    ],
    heroTag: "Marked HOT · sent to counsellor",
    heroAlt: "Anril WhatsApp AI agent replying to a customer enquiry for coaching centres, example chat in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for coaching centres and training institutes in India. It replies to course, batch and fee enquiries in seconds, sends brochures, marks each student Hot, Warm or Cold, and passes serious students to counsellors. Plans start from ₹999 a month.",
    asksH: "What students and parents ask",
    asksIntro:
      "Students and parents ask several institutes at the same time, mostly in the evening. The institute that replies first with clear fees and batch timings gets the demo class.",
    asks: [
      [
        { from: "them", who: "Student", text: "When does the next batch start?" },
        { from: "us", text: "Here are the upcoming batch dates. Which course are you interested in?" },
      ],
      [
        { from: "them", who: "Parent", text: "Online class or offline?" },
        { from: "us", text: "We have both. Here are the timings for each. Which suits you better?" },
      ],
      [
        { from: "them", who: "Student", text: "Is there an EMI option for fees?" },
        { from: "us", text: "Our counsellor will explain the payment options. What is a good time to call you?" },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds from your course list, batch timings, fees and brochure, in Tamil, English or Tanglish. Voice notes too."],
      ["Mark", "Each enquiry is marked Hot, Warm or Cold. A student asking for a demo class is Hot."],
      ["Pass on", "Hot leads go to your counsellor with the full chat. Warm leads get a follow-up message if they go quiet."],
    ],
    gets: [
      "Replies 24/7 on WhatsApp, Instagram, Facebook and Telegram, in one inbox",
      "Sends brochures, fee details and timetables in the chat",
      "Hot, Warm and Cold marks so counsellors call the right students first",
      "Bulk WhatsApp messages for new batches, results and offers, on the official WhatsApp API",
      "Call scoring for your counsellors' calls (Telecaller software)",
    ],
    shot: {
      caption: "Every course enquiry in one list, with the hottest students at the top.",
      alt: "Anril dashboard lead list for a coaching institute, with course enquiries marked Hot, Warm and Cold",
      rows: [
        { name: "Dhanush K", channel: "WhatsApp", note: "NEET weekend batch · demo class", score: "Hot", time: "3 min" },
        { name: "Meena (parent)", channel: "Instagram", note: "Online or offline batch", score: "Hot", time: "15 min" },
        { name: "Pranav S", channel: "WhatsApp", note: "Fee and EMI options", score: "Warm", time: "42 min" },
        { name: "Sneha R", channel: "Facebook", note: "Next batch start date", score: "Warm", time: "1 h" },
        { name: "Vignesh M", channel: "WhatsApp", note: "Asked about courses", score: "Cold", time: "4 h" },
      ],
    },
    faqs: [
      { q: "Does it reply in Tamil?", a: "Yes. Tanglish by default, and Tamil, English or any other language, based on how the student writes. It understands voice notes too." },
      { q: "Can it share our batch timings and fees?", a: "Yes. It answers from the course list, batches and fees you give us, and sends your brochure in the chat." },
      { q: "Can we tell all past enquiries about a new batch?", a: "Yes. Anril Reach sends bulk WhatsApp messages through the official WhatsApp API, to people who agreed to hear from you." },
      { q: "Can we check our counsellors' calls?", a: "Yes. The telecaller software records and scores each counsellor's calls, so you know who converts." },
      COST_FAQ,
    ],
    related: [IND.education, TELECALLER, PLANS],
  },
  {
    slug: "interiors-construction",
    path: "/industries/interiors-construction",
    label: "Interiors and construction",
    crumb: "Interiors & Construction",
    title: "WhatsApp AI Agent for Interior Designers & Builders | Anril AI",
    description:
      "Reply to every interior and construction enquiry in seconds, share past work photos, collect size, budget and location, and send serious clients to your team. From ₹999/month.",
    keywords: ["whatsapp chatbot for interior designers", "ai chatbot for interior designers", "whatsapp ai agent for interior designers", "interior designers lead management", "whatsapp automation for interior designers Tamil Nadu", "interior designers enquiry management software"],
    h1: "WhatsApp AI agent for interior designers and builders",
    line: "Anril replies to every enquiry at once, shares photos of your past work, asks size, budget and location, and sends serious clients to your team for a site visit.",
    heroChat: [
      { from: "them", text: "2BHK full interior evlo aagum?" },
      { from: "us", text: "It depends on the design and materials. Here are photos of our recent 2BHK work. What is your budget and where is the house?" },
      { from: "them", text: "Around 6 lakhs, Saravanampatti." },
      { from: "us", text: "Thanks! Our designer will call you to fix a site visit." },
    ],
    heroTag: "Marked HOT · sent to designer",
    heroAlt: "Anril WhatsApp AI agent replying to a customer enquiry for interior designers, example chat in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for interior designers and builders in India. It replies to enquiries in seconds, shares past work photos, asks size, budget and location, marks each client Hot, Warm or Cold, and sends serious clients to the team for a site visit. Plans start from ₹999 a month.",
    asksH: "What clients ask",
    asksIntro:
      "Home owners ask many interior designers and builders at once, mostly from Instagram and Facebook ads. The team that replies first and asks the right questions gets the site visit.",
    asks: [
      [
        { from: "them", who: "Client", text: "Do you do modular kitchens only?" },
        { from: "us", text: "Yes, we do modular kitchens and full home interiors. Here are some photos. Which one are you planning?" },
      ],
      [
        { from: "them", who: "Client", text: "How long does it take?" },
        { from: "us", text: "Our team will give the exact time after a site visit. Shall I arrange one?" },
      ],
      [
        { from: "them", who: "Client", text: "Do you do house construction also?" },
        { from: "us", text: "Yes. Please share the plot size and location, and our team will call you." },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with your services, past work photos and process from your information."],
      ["Qualify", "Asks size, budget, location and when they want to start. Marks each client Hot, Warm or Cold."],
      ["Pass on", "Clients asking for a site visit go to your team with the full chat and details."],
    ],
    gets: [
      "Instant replies to every ad and Instagram enquiry, even late at night",
      "Sends past work photos and brochures in the chat",
      "Hot, Warm and Cold marks so your team calls the right clients first",
      "Leads from Facebook and Instagram lead forms in the same list",
      "Bulk WhatsApp messages for offers and new work, on the official WhatsApp API",
    ],
    shot: {
      caption: "Every client with size, budget and location, ready for your team.",
      alt: "Anril dashboard lead list for an interior design firm, with clients' size, budget and location",
      rows: [
        { name: "Ramesh Kumar", channel: "Instagram", note: "2BHK interior · ₹6 L · site visit", score: "Hot", time: "4 min" },
        { name: "Divya S", channel: "Facebook", note: "Modular kitchen photos", score: "Hot", time: "18 min" },
        { name: "Karthik R", channel: "WhatsApp", note: "House construction · plot size", score: "Warm", time: "50 min" },
        { name: "Anitha P", channel: "Instagram", note: "How long it takes", score: "Warm", time: "2 h" },
        { name: "Gokul V", channel: "WhatsApp", note: "Price only", score: "Cold", time: "5 h" },
      ],
    },
    faqs: [
      { q: "Will it quote a price on its own?", a: "No. It shares only the price details you give it. Exact quotes come from your team after the site visit." },
      { q: "Can it send photos of our past work?", a: "Yes. It sends photos, brochures and videos you have added, right in the chat." },
      { q: "Can it reply to leads from our Facebook ads?", a: "Yes. Click-to-WhatsApp ads, Instagram DMs and lead forms all come into one list and get an instant reply." },
      { q: "Can our team take over a chat?", a: "Yes, any time. The full chat stays on screen." },
      COST_FAQ,
    ],
    related: [IND.realEstate, CRM, PLANS],
  },
  {
    slug: "retail",
    path: "/industries/retail",
    label: "Retail shops and boutiques",
    crumb: "Retail & Boutiques",
    title: "WhatsApp AI Agent for Retail Shops & Boutiques | Anril AI",
    description:
      "Answer every price, stock and colour question in seconds, send product photos and a Razorpay payment link in the chat, and track orders and stock. From ₹999/month.",
    keywords: ["whatsapp chatbot for retail shops", "ai chatbot for retail shops", "whatsapp ai agent for retail shops", "retail shops lead management", "whatsapp automation for retail shops Tamil Nadu", "retail shops enquiry management software"],
    h1: "WhatsApp AI agent for retail shops and boutiques",
    line: "Anril answers every 'price?', 'stock irukka?' and 'colour?' message at once, sends product photos and a payment link in the chat, and updates your stock after the order.",
    heroChat: [
      { from: "them", text: "Intha saree price evlo? Green colour irukka?" },
      { from: "us", text: "₹[price from your list]. Yes, green is in stock. Here are more photos." },
      { from: "them", text: "OK, I'll take it." },
      { from: "us", text: "Payment link", kind: "link" },
    ],
    heroTag: "Paid · order created",
    heroAlt: "Anril WhatsApp AI agent replying to a customer enquiry for retail shops, example chat in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for retail shops and boutiques in India. It answers price, stock and colour questions in seconds, sends product photos and Razorpay payment links in the chat, and tracks orders and stock in one place. Plans start from ₹999 a month.",
    asksH: "What customers ask",
    asksIntro:
      "Customers see your post or status and message at once. If nobody replies in a few minutes, they buy from the next shop.",
    asks: [
      [
        { from: "them", who: "Customer", text: "Shop timing enna?" },
        { from: "us", text: "We are open [from your details]. Here is our location." },
      ],
      [
        { from: "them", who: "Customer", text: "Delivery to Madurai possible?" },
        { from: "us", text: "Yes. Delivery usually takes [from your details]. Shall I send the payment link?" },
      ],
      [
        { from: "them", who: "Customer", text: "Bulk order for a function, discount kidaikkuma?" },
        { from: "us", text: "Our team will call you with the best offer. How many pieces do you need?" },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with price, sizes, colours, photos and stock from your catalogue."],
      ["Sell", "Sends a Razorpay payment link in the chat and shows paid, pending or failed."],
      ["Track", "The order is created, stock updates automatically, and you track dispatch."],
    ],
    gets: [
      "Replies 24/7 on WhatsApp, Instagram and Facebook",
      "Sends product photos and price lists in the chat",
      "Payment links in the chat (UPI, cards, net banking through Razorpay)",
      "Orders, GST invoices and stock with low-stock alerts (Anril Commerce)",
      "Bulk WhatsApp messages for new arrivals and offers, on the official WhatsApp API",
    ],
    shot: {
      caption: "From enquiry to paid order, in one place.",
      alt: "Anril dashboard lead list for a boutique, with paid orders and open enquiries",
      rows: [
        { name: "Lakshmi N", channel: "WhatsApp", note: "Green saree · paid", score: "Hot", time: "2 min" },
        { name: "Priya M", channel: "Instagram", note: "Payment link sent", score: "Hot", time: "10 min" },
        { name: "Revathi S", channel: "WhatsApp", note: "Bulk order for a function", score: "Warm", time: "35 min" },
        { name: "Shalini K", channel: "Facebook", note: "Delivery to Madurai", score: "Warm", time: "1 h" },
        { name: "Deepa R", channel: "WhatsApp", note: "Shop timing", score: "Cold", time: "3 h" },
      ],
    },
    faqs: [
      { q: "Can customers pay inside the chat?", a: "Yes. The AI sends a Razorpay payment link, and you see whether it is paid, pending or failed." },
      { q: "Does stock update by itself?", a: "Yes. Stock updates after each order, and you get low-stock alerts." },
      { q: "Can it understand photos customers send?", a: "Not yet. If a customer sends a photo, Anril asks them to type their question, and the photo stays in the chat for your team to see." },
      { q: "Can we send new arrivals to old customers?", a: "Yes. Anril Reach sends bulk WhatsApp messages to customers who agreed to hear from you." },
      COST_FAQ,
    ],
    related: [IND.d2c, PAYMENTS, PLANS],
  },
  {
    slug: "jewellery",
    path: "/industries/jewellery",
    label: "Jewellery shops",
    crumb: "Jewellery",
    title: "WhatsApp AI Agent for Jewellery Shops | Anril AI",
    description:
      "Reply to every design, weight and price enquiry in seconds, share design photos, and send serious buyers to your store team. From ₹999/month.",
    keywords: ["whatsapp chatbot for jewellery shops", "ai chatbot for jewellery shops", "whatsapp ai agent for jewellery shops", "jewellery shops lead management", "whatsapp automation for jewellery shops Tamil Nadu", "jewellery shops enquiry management software"],
    h1: "WhatsApp AI agent for jewellery shops",
    line: "Anril replies to every design and price enquiry at once, shares photos of your designs, and sends serious buyers to your store team.",
    heroChat: [
      { from: "them", text: "Bridal necklace designs anuppunga. Budget around 3 lakhs." },
      { from: "us", text: "Here are some bridal designs in that range. Would you like to visit the store?" },
      { from: "them", text: "Sunday varalama?" },
      { from: "us", text: "Sure! Our store team will call you to confirm Sunday." },
    ],
    heroTag: "Marked HOT · sent to store",
    heroAlt: "Anril WhatsApp AI agent replying to a customer enquiry for jewellery shops, example chat in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for jewellery shops in India. It replies to design and price enquiries in seconds, shares design photos, marks each buyer Hot, Warm or Cold, and sends serious buyers to the store team. Plans start from ₹999 a month.",
    asksH: "What buyers ask",
    asksIntro:
      "Buyers want to see designs before they visit. The shop that sends good photos and replies first gets the store visit.",
    asks: [
      [
        { from: "them", who: "Customer", text: "Today gold rate enna?" },
        { from: "us", text: "Our team updates today's rate here: [from your details]. Would you like to see designs?" },
      ],
      [
        { from: "them", who: "Customer", text: "Old gold exchange irukka?" },
        { from: "us", text: "Yes. Our store team will explain the exchange. What is a good time to call?" },
      ],
      [
        { from: "them", who: "Customer", text: "Do you have light-weight chains?" },
        { from: "us", text: "Here are some light-weight designs. Which length do you like?" },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with design photos, weights and details from your information."],
      ["Qualify", "Asks what they are looking for, budget and occasion. Marks each buyer Hot, Warm or Cold."],
      ["Pass on", "Buyers who want to visit or book go to your store team with the full chat."],
    ],
    gets: [
      "Replies 24/7 on WhatsApp, Instagram and Facebook",
      "Sends design photos and catalogues in the chat",
      "Hot, Warm and Cold marks so your team calls the right buyers first",
      "Bulk WhatsApp messages for festival offers and new collections, on the official WhatsApp API",
      "Payment links for advance bookings (Razorpay)",
    ],
    shot: {
      caption: "Every buyer with budget and occasion, ready for your store team.",
      alt: "Anril dashboard lead list for a jewellery shop, with buyers' budget and occasion",
      rows: [
        { name: "Saranya V", channel: "WhatsApp", note: "Bridal necklace · ₹3 L · Sunday visit", score: "Hot", time: "5 min" },
        { name: "Murugan P", channel: "WhatsApp", note: "Old gold exchange", score: "Hot", time: "20 min" },
        { name: "Kavitha R", channel: "Instagram", note: "Light-weight chains", score: "Warm", time: "45 min" },
        { name: "Bhavani S", channel: "Facebook", note: "Festival offer", score: "Warm", time: "2 h" },
        { name: "Arun K", channel: "WhatsApp", note: "Today's rate", score: "Cold", time: "4 h" },
      ],
    },
    faqs: [
      { q: "Will it tell customers today's gold rate?", a: "Only the rate your team updates. It never guesses a price." },
      { q: "Can it send design photos?", a: "Yes. It sends the photos and catalogues you have added, right in the chat." },
      { q: "Can customers pay an advance?", a: "Yes. The AI can send a Razorpay payment link, and you see whether it is paid." },
      { q: "Can we send festival offers to old customers?", a: "Yes. Anril Reach sends bulk WhatsApp messages to customers who agreed to hear from you." },
      COST_FAQ,
    ],
    related: [IND.retail, BULK, PLANS],
  },
  {
    slug: "salons-beauty",
    path: "/industries/salons-beauty",
    label: "Salons, beauty and spas",
    crumb: "Salons & Beauty",
    title: "WhatsApp AI Agent for Salons, Beauty Parlours & Spas | Anril AI",
    description:
      "Answer every service and price question in seconds, collect appointment requests, and send them to your front desk. Makeup artists too. From ₹999/month.",
    keywords: ["whatsapp chatbot for salons", "ai chatbot for salons", "whatsapp ai agent for salons", "salons lead management", "whatsapp automation for salons Tamil Nadu", "salons enquiry management software"],
    h1: "WhatsApp AI agent for salons, beauty parlours and spas",
    line: "Anril answers every service and price question from your list, collects appointment requests, and sends them to your front desk, even when you are busy with a customer.",
    heroChat: [
      { from: "them", text: "Bridal makeup package evlo?" },
      { from: "us", text: "Here are our bridal packages and photos of our work. What is the wedding date?" },
      { from: "them", text: "15 Feb, Coimbatore." },
      { from: "us", text: "Thank you! Our team will call you to confirm the booking." },
    ],
    heroTag: "Booking request · sent to team",
    heroAlt: "Anril WhatsApp AI agent replying to a customer enquiry for salons, example chat in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for salons, beauty parlours, spas and makeup artists in India. It answers service and price questions in seconds, collects appointment requests for the front desk, and sends bridal and package enquiries to the team. Plans start from ₹999 a month.",
    asksH: "What customers ask",
    asksIntro:
      "Customers message while you are busy with someone in the chair. If nobody replies, they book somewhere else.",
    asks: [
      [
        { from: "them", who: "Customer", text: "Haircut today evening slot irukka?" },
        { from: "us", text: "Please share your preferred time, and our front desk will confirm the slot." },
      ],
      [
        { from: "them", who: "Customer", text: "Facial price list?" },
        { from: "us", text: "Here is our price list. Which service would you like?" },
      ],
      [
        { from: "them", who: "Customer", text: "Do you have a membership offer?" },
        { from: "us", text: "Here are our membership details. Shall I ask our team to call you?" },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with services, prices and photos from your list."],
      ["Collect", "Takes the customer's name, service and preferred time for an appointment request."],
      ["Pass on", "Your front desk confirms. Bridal and package enquiries are marked Hot and sent to your team."],
    ],
    gets: [
      "Replies 24/7 in Tamil, English or Tanglish, including voice notes",
      "Sends price lists and photos of your work in the chat",
      "Appointment requests collected in the chat",
      "Payment links for advance bookings (Razorpay)",
      "Bulk WhatsApp messages for festival offers, to customers who agreed to hear from you",
    ],
    shot: {
      caption: "Every appointment request in one list for your front desk.",
      alt: "Anril dashboard lead list for a salon, with appointment requests for the front desk",
      rows: [
        { name: "Nivetha R", channel: "Instagram", note: "Bridal makeup · 15 Feb", score: "Hot", time: "3 min" },
        { name: "Pooja S", channel: "WhatsApp", note: "Haircut · today 6 pm", score: "Hot", time: "12 min" },
        { name: "Malini K", channel: "WhatsApp", note: "Facial price list", score: "Warm", time: "40 min" },
        { name: "Sangeetha P", channel: "Facebook", note: "Membership offer", score: "Warm", time: "1 h" },
        { name: "Yamini V", channel: "WhatsApp", note: "Asked about services", score: "Cold", time: "5 h" },
      ],
    },
    faqs: [
      { q: "Does it book the appointment itself?", a: "It collects the request and preferred time. Your front desk confirms it." },
      { q: "Can it take an advance for bridal bookings?", a: "Yes. The AI can send a Razorpay payment link, and you see whether it is paid." },
      { q: "Does it work for freelance makeup artists?", a: "Yes. It answers your enquiries and sends bookings to you, even when you are at a wedding." },
      { q: "Can we send offers to our regular customers?", a: "Yes. Anril Reach sends bulk WhatsApp messages to customers who agreed to hear from you." },
      COST_FAQ,
    ],
    related: [IND.healthcare, BULK, PLANS],
  },
  {
    slug: "gyms-fitness",
    path: "/industries/gyms-fitness",
    label: "Gyms and fitness",
    crumb: "Gyms & Fitness",
    title: "WhatsApp AI Agent for Gyms & Fitness Studios | Anril AI",
    description:
      "Answer membership, timing and fee questions in seconds, collect trial-visit requests, and follow up when someone goes quiet. From ₹999/month.",
    keywords: ["whatsapp chatbot for gyms", "ai chatbot for gyms", "whatsapp ai agent for gyms", "gyms lead management", "whatsapp automation for gyms Tamil Nadu", "gyms enquiry management software"],
    h1: "WhatsApp AI agent for gyms and fitness studios",
    line: "Anril answers membership, timing and fee questions at once, collects trial-visit requests, and follows up with people who go quiet.",
    heroChat: [
      { from: "them", text: "Monthly fees evlo? Ladies batch irukka?" },
      { from: "us", text: "Here are our plans and timings. Yes, we have a ladies batch. Would you like a trial visit?" },
      { from: "them", text: "Tomorrow morning." },
      { from: "us", text: "Great! Our trainer will call you to confirm." },
    ],
    heroTag: "Trial request · sent to trainer",
    heroAlt: "Anril WhatsApp AI agent replying to a customer enquiry for gyms, example chat in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for gyms and fitness studios in India. It answers membership, timing and fee questions in seconds, collects trial-visit requests, follows up with people who go quiet, and sends payment links. Plans start from ₹999 a month.",
    asksH: "What people ask",
    asksIntro:
      "People decide to join a gym in a moment of motivation. If nobody replies quickly, that moment passes.",
    asks: [
      [
        { from: "them", who: "Customer", text: "Personal trainer available?" },
        { from: "us", text: "Yes. Here are the personal training plans. Shall our trainer call you?" },
      ],
      [
        { from: "them", who: "Customer", text: "Yoga or Zumba classes?" },
        { from: "us", text: "Here are the class timings. Which one would you like to try?" },
      ],
      [
        { from: "them", who: "Customer", text: "Parking irukka?" },
        { from: "us", text: "Yes. Here is our location and parking details." },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with plans, fees, timings and classes from your information."],
      ["Collect", "Takes name, goal and preferred time for a trial visit."],
      ["Follow up", "Sends a follow-up message when someone goes quiet, and sends trial requests to your trainer."],
    ],
    gets: [
      "Replies 24/7 on WhatsApp, Instagram and Facebook",
      "Trial-visit requests collected in the chat",
      "Follow-up message when someone goes quiet",
      "Payment links for memberships (Razorpay)",
      "Bulk WhatsApp messages for offers and renewals, to members who agreed to hear from you",
    ],
    shot: {
      caption: "Every trial request and enquiry in one list.",
      alt: "Anril dashboard lead list for a gym, with trial requests and enquiries",
      rows: [
        { name: "Harish M", channel: "Instagram", note: "Trial visit · tomorrow morning", score: "Hot", time: "2 min" },
        { name: "Keerthana S", channel: "WhatsApp", note: "Ladies batch · monthly fee", score: "Hot", time: "16 min" },
        { name: "Rahul P", channel: "WhatsApp", note: "Personal trainer plans", score: "Warm", time: "38 min" },
        { name: "Swathi R", channel: "Facebook", note: "Yoga and Zumba timings", score: "Warm", time: "2 h" },
        { name: "Ajith K", channel: "WhatsApp", note: "Parking", score: "Cold", time: "6 h" },
      ],
    },
    faqs: [
      { q: "Can members pay online?", a: "Yes. The AI can send a Razorpay payment link, and you see whether it is paid." },
      { q: "Can it remind members to renew?", a: "Yes. Anril Reach sends WhatsApp messages to members who agreed to hear from you." },
      { q: "Does it reply in Tamil?", a: "Yes. Tanglish by default, and Tamil, English or any other language, including voice notes." },
      { q: "Can our trainers take over a chat?", a: "Yes, any time. The full chat stays on screen." },
      COST_FAQ,
    ],
    related: [IND.salons, BULK, PLANS],
  },
  {
    slug: "travel-tours",
    path: "/industries/travel-tours",
    label: "Travel and tours",
    crumb: "Travel & Tours",
    title: "WhatsApp AI Agent for Travel Agencies & Tour Operators | Anril AI",
    description:
      "Reply to every package enquiry in seconds, share itineraries, collect dates, people and budget, and send serious travellers to your team. From ₹999/month.",
    keywords: ["whatsapp chatbot for travel agencies", "ai chatbot for travel agencies", "whatsapp ai agent for travel agencies", "travel agencies lead management", "whatsapp automation for travel agencies Tamil Nadu", "travel agencies enquiry management software"],
    h1: "WhatsApp AI agent for travel agencies and tour operators",
    line: "Anril replies to every package enquiry at once, shares itineraries and photos, asks dates, number of people and budget, and sends serious travellers to your team.",
    heroChat: [
      { from: "them", text: "Kerala 3 days package for 4 people evlo?" },
      { from: "us", text: "Here is our Kerala package and itinerary. Which dates are you planning?" },
      { from: "them", text: "Dec 20 to 23." },
      { from: "us", text: "Thanks! Our travel expert will call you with the final price." },
    ],
    heroTag: "Marked HOT · sent to travel expert",
    heroAlt: "Anril WhatsApp AI agent replying to a customer enquiry for travel agencies, example chat in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for travel agencies and tour operators in India. It replies to package enquiries in seconds, shares itineraries, collects dates, people and budget, marks each traveller Hot, Warm or Cold, and sends serious travellers to the team. Plans start from ₹999 a month.",
    asksH: "What travellers ask",
    asksIntro:
      "Travellers ask several agencies at once, often at night. The agency that replies first with a clear plan gets the booking.",
    asks: [
      [
        { from: "them", who: "Traveller", text: "Do you do Dubai packages?" },
        { from: "us", text: "Yes. Here is our Dubai package. How many people and which month?" },
      ],
      [
        { from: "them", who: "Traveller", text: "Visa help kidaikkuma?" },
        { from: "us", text: "Our team will explain the visa process. What is a good time to call?" },
      ],
      [
        { from: "them", who: "Traveller", text: "Is hotel included?" },
        { from: "us", text: "Here is what the package includes. Shall I ask our team for a quote?" },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with packages, itineraries and photos from your information."],
      ["Collect", "Asks destination, dates, number of people and budget, one question at a time."],
      ["Pass on", "Serious travellers are marked Hot and sent to your team with every detail."],
    ],
    gets: [
      "Replies 24/7 on WhatsApp, Instagram and Facebook",
      "Sends itineraries, PDFs and photos in the chat",
      "Hot, Warm and Cold marks on every enquiry",
      "Payment links for advance bookings (Razorpay)",
      "Bulk WhatsApp messages for new packages and offers, on the official WhatsApp API",
    ],
    shot: {
      caption: "Every traveller with dates, people and budget, ready for your team.",
      alt: "Anril dashboard lead list for a travel agency, with travellers' dates, people and budget",
      rows: [
        { name: "Senthil Kumar", channel: "WhatsApp", note: "Kerala · 4 people · Dec 20–23", score: "Hot", time: "4 min" },
        { name: "Fathima B", channel: "Instagram", note: "Dubai package · March", score: "Hot", time: "22 min" },
        { name: "Naveen R", channel: "WhatsApp", note: "Visa help", score: "Warm", time: "48 min" },
        { name: "Gayathri S", channel: "Facebook", note: "Is hotel included?", score: "Warm", time: "2 h" },
        { name: "Manoj P", channel: "WhatsApp", note: "Asked about packages", score: "Cold", time: "5 h" },
      ],
    },
    faqs: [
      { q: "Will it confirm prices on its own?", a: "Only the package prices you give it. Custom quotes come from your team." },
      { q: "Can it send our itinerary PDFs?", a: "Yes. It sends your itineraries, brochures and photos in the chat." },
      { q: "Can customers pay an advance?", a: "Yes. The AI can send a Razorpay payment link, and you see whether it is paid." },
      { q: "Can we send new packages to past travellers?", a: "Yes. Anril Reach sends bulk WhatsApp messages to people who agreed to hear from you." },
      COST_FAQ,
    ],
    related: [IND.hotels, BULK, PLANS],
  },
  {
    slug: "hotels-resorts",
    path: "/industries/hotels-resorts",
    label: "Hotels and resorts",
    crumb: "Hotels & Resorts",
    title: "WhatsApp AI Agent for Hotels, Resorts & Homestays | Anril AI",
    description:
      "Answer room, rate and facility questions in seconds, collect booking requests, and send them to your front desk. From ₹999/month.",
    keywords: ["whatsapp chatbot for hotels", "ai chatbot for hotels", "whatsapp ai agent for hotels", "hotels lead management", "whatsapp automation for hotels Tamil Nadu", "hotels enquiry management software"],
    h1: "WhatsApp AI agent for hotels, resorts and homestays",
    line: "Anril answers room, rate and facility questions at once from your details, collects booking requests, and sends them to your front desk.",
    heroChat: [
      { from: "them", text: "Room available for Dec 24, 2 adults?" },
      { from: "us", text: "Here are our room types and photos. Our front desk will confirm availability for Dec 24." },
      { from: "them", text: "Breakfast included?" },
      { from: "us", text: "Yes, breakfast is included with these rooms. Shall I send your request to the front desk?" },
    ],
    heroTag: "Booking request · sent to front desk",
    heroAlt: "Anril WhatsApp AI agent replying to a customer enquiry for hotels, example chat in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for hotels, resorts and homestays in India. It answers room, rate and facility questions in seconds, collects booking requests for the front desk, and sends payment links for advances. Plans start from ₹999 a month.",
    asksH: "What guests ask",
    asksIntro:
      "Guests compare places quickly and book the one that answers first. Your front desk can't reply to everyone at night.",
    asks: [
      [
        { from: "them", who: "Guest", text: "Check-in time?" },
        { from: "us", text: "Check-in is [from your details]. Would you like to book?" },
      ],
      [
        { from: "them", who: "Guest", text: "Pet friendly ah?" },
        { from: "us", text: "Here is our pet policy. Anything else I can help with?" },
      ],
      [
        { from: "them", who: "Guest", text: "Group booking for 20 people?" },
        { from: "us", text: "Our team will call you with a group quote. Which dates?" },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with rooms, rates, photos and facilities from your details."],
      ["Collect", "Takes dates, number of guests and room type for a booking request."],
      ["Pass on", "Your front desk confirms availability and the booking."],
    ],
    gets: [
      "Replies 24/7 in Tamil, English or any language",
      "Sends room photos and rate cards in the chat",
      "Booking requests collected in the chat",
      "Payment links for advance payment (Razorpay)",
      "Bulk WhatsApp messages for offers, to past guests who agreed to hear from you",
    ],
    shot: {
      caption: "Every booking request in one list for your front desk.",
      alt: "Anril dashboard lead list for a resort, with booking requests for the front desk",
      rows: [
        { name: "Vikram S", channel: "WhatsApp", note: "Dec 24 · 2 adults · breakfast", score: "Hot", time: "3 min" },
        { name: "Asha R", channel: "Instagram", note: "Group booking · 20 people", score: "Hot", time: "14 min" },
        { name: "Joseph M", channel: "WhatsApp", note: "Check-in time", score: "Warm", time: "36 min" },
        { name: "Nisha K", channel: "Facebook", note: "Pet policy", score: "Warm", time: "1 h" },
        { name: "Rohit P", channel: "WhatsApp", note: "Room rates", score: "Cold", time: "4 h" },
      ],
    },
    faqs: [
      { q: "Does it check room availability itself?", a: "No. It collects the request, and your front desk confirms availability." },
      { q: "Can guests pay an advance?", a: "Yes. The AI can send a Razorpay payment link, and you see whether it is paid." },
      { q: "Can it reply in other languages?", a: "Yes. It replies in the language the guest uses, including voice notes." },
      { q: "Can we send offers to past guests?", a: "Yes. Anril Reach sends bulk WhatsApp messages to guests who agreed to hear from you." },
      COST_FAQ,
    ],
    related: [IND.travel, PAYMENTS, PLANS],
  },
  {
    slug: "restaurants",
    path: "/industries/restaurants",
    label: "Restaurants and cloud kitchens",
    crumb: "Restaurants",
    title: "WhatsApp AI Agent for Restaurants & Cloud Kitchens | Anril AI",
    description:
      "Share your menu in seconds, answer timing and location questions, collect party and bulk order enquiries, and send them to your team. From ₹999/month.",
    keywords: ["whatsapp chatbot for restaurants", "ai chatbot for restaurants", "whatsapp ai agent for restaurants", "restaurants lead management", "whatsapp automation for restaurants Tamil Nadu", "restaurants enquiry management software"],
    h1: "WhatsApp AI agent for restaurants and cloud kitchens",
    line: "Anril shares your menu at once, answers timing and location questions, and collects party, catering and bulk order enquiries for your team.",
    heroChat: [
      { from: "them", text: "Birthday party for 40 people, menu and price?" },
      { from: "us", text: "Here is our party menu. Which date and time are you planning?" },
      { from: "them", text: "Saturday night." },
      { from: "us", text: "Thanks! Our manager will call you to confirm." },
    ],
    heroTag: "Marked HOT · sent to manager",
    heroAlt: "Anril WhatsApp AI agent replying to a customer enquiry for restaurants, example chat in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for restaurants and cloud kitchens in India. It shares the menu in seconds, answers timing and location questions, and collects party, catering and table requests for the team. Plans start from ₹999 a month.",
    asksH: "What customers ask",
    asksIntro:
      "Big orders and party bookings come on WhatsApp while your team is busy in the kitchen. A quick reply wins the order.",
    asks: [
      [
        { from: "them", who: "Customer", text: "Menu anuppunga." },
        { from: "us", text: "Here is today's menu. Would you like to order?" },
      ],
      [
        { from: "them", who: "Customer", text: "Table booking for 6 tonight?" },
        { from: "us", text: "Please share the time, and our team will confirm your table." },
      ],
      [
        { from: "them", who: "Customer", text: "Catering for a wedding?" },
        { from: "us", text: "Yes. How many guests and which date? Our team will call you." },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with your menu, timings and location."],
      ["Collect", "Takes date, time and number of people for party, catering and table requests."],
      ["Pass on", "Your team confirms. Big orders are marked Hot."],
    ],
    gets: [
      "Replies 24/7 on WhatsApp, Instagram and Facebook",
      "Sends your menu and photos in the chat",
      "Party, catering and table requests collected in the chat",
      "Payment links for advance orders (Razorpay)",
      "Bulk WhatsApp messages for offers, to customers who agreed to hear from you",
    ],
    shot: {
      caption: "Every party and catering enquiry in one list.",
      alt: "Anril dashboard lead list for a restaurant, with party and catering enquiries",
      rows: [
        { name: "Balaji R", channel: "WhatsApp", note: "Birthday party · 40 people · Saturday", score: "Hot", time: "5 min" },
        { name: "Sowmya K", channel: "Instagram", note: "Wedding catering", score: "Hot", time: "18 min" },
        { name: "Prakash M", channel: "WhatsApp", note: "Table for 6 tonight", score: "Warm", time: "30 min" },
        { name: "Hema S", channel: "Facebook", note: "Weekend offer", score: "Warm", time: "2 h" },
        { name: "Dinesh V", channel: "WhatsApp", note: "Menu", score: "Cold", time: "3 h" },
      ],
    },
    faqs: [
      { q: "Does it take food orders from Swiggy or Zomato?", a: "No. It handles chats that come to your own WhatsApp, Instagram and Facebook." },
      { q: "Can customers pay an advance for a party?", a: "Yes. The AI can send a Razorpay payment link, and you see whether it is paid." },
      { q: "Does it book tables itself?", a: "It collects the request. Your team confirms it." },
      { q: "Can we send weekend offers?", a: "Yes. Anril Reach sends bulk WhatsApp messages to customers who agreed to hear from you." },
      COST_FAQ,
    ],
    related: [IND.events, BULK, PLANS],
  },
  {
    slug: "events-weddings",
    path: "/industries/events-weddings",
    label: "Events and weddings",
    crumb: "Events & Weddings",
    title: "WhatsApp AI Agent for Event Planners & Wedding Services | Anril AI",
    description:
      "Reply to every event enquiry in seconds, share past work photos and packages, collect date, venue and budget, and send serious clients to your team. From ₹999/month.",
    keywords: ["whatsapp chatbot for event planners", "ai chatbot for event planners", "whatsapp ai agent for event planners", "event planners lead management", "whatsapp automation for event planners Tamil Nadu", "event planners enquiry management software"],
    h1: "WhatsApp AI agent for event planners and wedding services",
    line: "Anril replies to every enquiry at once, shares photos of your past events and packages, asks date, venue and budget, and sends serious clients to your team.",
    heroChat: [
      { from: "them", text: "Wedding stage decoration price evlo?" },
      { from: "us", text: "Here are photos of our recent stage work and packages. What is the date and venue?" },
      { from: "them", text: "March 10, Coimbatore. Budget 1.5 lakhs." },
      { from: "us", text: "Thanks! Our team will call you today." },
    ],
    heroTag: "Marked HOT · sent to team",
    heroAlt: "Anril WhatsApp AI agent replying to a customer enquiry for event planners, example chat in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for event planners, decorators and wedding services in India. It replies to enquiries in seconds, shares past work photos and packages, asks date, venue and budget, and sends serious clients to the team. Plans start from ₹999 a month.",
    asksH: "What clients ask",
    asksIntro:
      "Families ask many decorators, photographers and planners at once. The one who replies first with good photos gets the meeting.",
    asks: [
      [
        { from: "them", who: "Client", text: "Is March 10 available?" },
        { from: "us", text: "Our team will confirm the date. Which venue is it?" },
      ],
      [
        { from: "them", who: "Client", text: "Do you do birthday decoration also?" },
        { from: "us", text: "Yes. Here are some birthday setups. Which date?" },
      ],
      [
        { from: "them", who: "Client", text: "Can we see the full album?" },
        { from: "us", text: "Here are more photos. Shall our team call you?" },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with packages and photos of your past work."],
      ["Qualify", "Asks date, venue, number of guests and budget. Marks each client Hot, Warm or Cold."],
      ["Pass on", "Serious clients go to your team with the full chat."],
    ],
    gets: [
      "Instant replies to every ad and Instagram enquiry",
      "Sends past work photos and packages in the chat",
      "Hot, Warm and Cold marks so you call the right clients first",
      "Payment links for advance bookings (Razorpay)",
      "Bulk WhatsApp messages for wedding season offers, on the official WhatsApp API",
    ],
    shot: {
      caption: "Every client with date, venue and budget, ready for your team.",
      alt: "Anril dashboard lead list for an event decorator, with clients' date, venue and budget",
      rows: [
        { name: "Jayanthi R", channel: "Instagram", note: "Stage decoration · March 10 · ₹1.5 L", score: "Hot", time: "3 min" },
        { name: "Suresh P", channel: "WhatsApp", note: "Is March 10 available?", score: "Hot", time: "20 min" },
        { name: "Abirami K", channel: "Facebook", note: "Birthday decoration", score: "Warm", time: "45 min" },
        { name: "Madhan S", channel: "Instagram", note: "Full album", score: "Warm", time: "2 h" },
        { name: "Renuka V", channel: "WhatsApp", note: "Price only", score: "Cold", time: "5 h" },
      ],
    },
    faqs: [
      { q: "Does it check if our date is free?", a: "No. It collects the date, and your team confirms." },
      { q: "Can it send photos of our work?", a: "Yes. It sends the photos and videos you have added, right in the chat." },
      { q: "Can clients pay an advance?", a: "Yes. The AI can send a Razorpay payment link, and you see whether it is paid." },
      { q: "Can it reply to leads from our Instagram ads?", a: "Yes. Instagram, Facebook and WhatsApp enquiries all come into one list." },
      COST_FAQ,
    ],
    related: [IND.restaurants, CRM, PLANS],
  },
  {
    slug: "home-services",
    path: "/industries/home-services",
    label: "Home services and repairs",
    crumb: "Home Services",
    title: "WhatsApp AI Agent for Home Services & Repairs | Anril AI",
    description:
      "Collect the problem, address and preferred time for every service request in seconds, and send the job to your team. AC, plumbing, pest control and more. From ₹999/month.",
    keywords: ["whatsapp chatbot for home services", "ai chatbot for home services", "whatsapp ai agent for home services", "home services lead management", "whatsapp automation for home services Tamil Nadu", "home services enquiry management software"],
    h1: "WhatsApp AI agent for home services and repairs",
    line: "Anril replies to every service request at once, collects the problem, address and preferred time, and sends the job to your team.",
    heroChat: [
      { from: "them", text: "AC not cooling. Today service possible?" },
      { from: "us", text: "Sorry to hear that. Which AC brand, and what is your area?" },
      { from: "them", text: "LG, RS Puram. Evening ok." },
      { from: "us", text: "Thanks! Our team will call you to confirm the evening visit." },
    ],
    heroTag: "Job request · sent to team",
    heroAlt: "Anril WhatsApp AI agent replying to a customer enquiry for home services, example chat in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for home service and repair businesses in India. It replies to service requests in seconds, collects the problem, address and preferred time, and sends the job to the team. Plans start from ₹999 a month.",
    asksH: "What customers ask",
    asksIntro:
      "When something breaks, customers message 3 or 4 service providers. The first one to reply clearly gets the job.",
    asks: [
      [
        { from: "them", who: "Customer", text: "Service charge evlo?" },
        { from: "us", text: "Our visit charge is [from your details]. Shall I book a visit?" },
      ],
      [
        { from: "them", who: "Customer", text: "Pest control for 2BHK?" },
        { from: "us", text: "Here are our pest control packages. Which area are you in?" },
      ],
      [
        { from: "them", who: "Customer", text: "Plumber urgent ah venum." },
        { from: "us", text: "Please share your address. I'm passing this to our team now." },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with services and charges from your information."],
      ["Collect", "Takes the problem, address and preferred time, one question at a time."],
      ["Pass on", "The job request goes to your team to confirm and assign."],
    ],
    gets: [
      "Replies 24/7 in Tamil, English or Tanglish, including voice notes",
      "Job requests with problem, address and time collected in the chat",
      "Payment links after the job (Razorpay)",
      "Bulk WhatsApp messages for service reminders, to customers who agreed to hear from you",
      "Call scoring for your team's calls (Telecaller software)",
    ],
    shot: {
      caption: "Every job request in one list, ready to assign.",
      alt: "Anril dashboard lead list for a home services business, with job requests ready to assign",
      rows: [
        { name: "Ganesh K", channel: "WhatsApp", note: "AC not cooling · RS Puram · evening", score: "Hot", time: "2 min" },
        { name: "Latha M", channel: "WhatsApp", note: "Plumber · urgent", score: "Hot", time: "9 min" },
        { name: "Sathish R", channel: "Facebook", note: "Pest control · 2BHK", score: "Warm", time: "40 min" },
        { name: "Usha P", channel: "Instagram", note: "Service charge", score: "Warm", time: "1 h" },
        { name: "Kumar S", channel: "WhatsApp", note: "Yearly service", score: "Cold", time: "4 h" },
      ],
    },
    faqs: [
      { q: "Does it assign the technician itself?", a: "No. It collects the job details, and your team assigns it." },
      { q: "Can customers pay online after the job?", a: "Yes. The AI can send a Razorpay payment link, and you see whether it is paid." },
      { q: "Can we remind customers about yearly service?", a: "Yes. Anril Reach sends WhatsApp reminders to customers who agreed to hear from you." },
      { q: "Does it understand voice notes?", a: "Yes. Many customers send voice notes, and it understands them." },
      COST_FAQ,
    ],
    related: [TELECALLER, BULK, PLANS],
  },
  {
    slug: "professional-services",
    path: "/industries/professional-services",
    label: "CA, law and consultants",
    crumb: "CA, Law & Consultants",
    title: "WhatsApp AI Agent for CA Firms, Lawyers & Consultants | Anril AI",
    description:
      "Answer common questions in seconds, collect what the client needs, and book a call with your team. Never gives legal or tax advice. From ₹999/month.",
    keywords: ["whatsapp chatbot for CA firms", "ai chatbot for CA firms", "whatsapp ai agent for CA firms", "CA firms lead management", "whatsapp automation for CA firms Tamil Nadu", "CA firms enquiry management software"],
    h1: "WhatsApp AI agent for CA firms, lawyers and consultants",
    line: "Anril answers common questions about your services and documents, collects what the client needs, and books a call with your team. It never gives legal or tax advice.",
    heroChat: [
      { from: "them", text: "GST registration panna evlo charge?" },
      { from: "us", text: "Here are the details and the documents needed. What kind of business do you run?" },
      { from: "them", text: "Small textile shop." },
      { from: "us", text: "Thanks! Our team will call you today." },
    ],
    heroTag: "Marked HOT · sent to team",
    heroAlt: "Anril WhatsApp AI agent replying to a customer enquiry for CA firms, example chat in Tanglish",
    quickAnswer:
      "Anril AI is a WhatsApp AI agent for CA firms, lawyers and consultants in India. It answers common questions about services and documents in seconds, collects what the client needs, and books a call with the team. It never gives legal or tax advice. Plans start from ₹999 a month.",
    asksH: "What clients ask",
    asksIntro:
      "Clients want a quick answer about services and documents before they call. Your team is busy with client work.",
    asks: [
      [
        { from: "them", who: "Client", text: "ITR filing documents list?" },
        { from: "us", text: "Here is the document list. Shall our team call you?" },
      ],
      [
        { from: "them", who: "Client", text: "Property document verification panna mudiyuma?" },
        { from: "us", text: "Yes. Our team will call you to understand the case. What is a good time?" },
      ],
      [
        { from: "them", who: "Client", text: "Do you do company registration?" },
        { from: "us", text: "Yes. Here is how it works. Shall I book a call with our team?" },
      ],
    ],
    steps: [
      ["Answer", "Replies in seconds with your services, fees and document lists from your information."],
      ["Collect", "Takes the client's name, city and what they need."],
      ["Pass on", "Serious clients go to your team for a call. Legal and tax questions always go to a person."],
    ],
    gets: [
      "Replies 24/7 on WhatsApp, Instagram and Facebook",
      "Sends document lists and service details in the chat",
      "Hot, Warm and Cold marks on every enquiry",
      "Follow-up message when a client goes quiet",
      "Payment links for fees (Razorpay)",
    ],
    shot: {
      caption: "Every client enquiry with what they need, ready for your team.",
      alt: "Anril dashboard lead list for a CA firm, with each client's need",
      rows: [
        { name: "Raghav T", channel: "WhatsApp", note: "GST registration · textile shop", score: "Hot", time: "4 min" },
        { name: "Selvi M", channel: "WhatsApp", note: "Property document check", score: "Hot", time: "25 min" },
        { name: "Arvind K", channel: "Facebook", note: "Company registration", score: "Warm", time: "50 min" },
        { name: "Pavithra S", channel: "Instagram", note: "ITR filing documents", score: "Warm", time: "2 h" },
        { name: "Mohan R", channel: "WhatsApp", note: "Fees", score: "Cold", time: "5 h" },
      ],
    },
    faqs: [
      { q: "Will the AI give legal or tax advice?", a: "No. It shares only your service details and document lists. Advice always comes from your team." },
      { q: "Is client data safe?", a: "We use the official WhatsApp Business API, and chats stay in your own dashboard. See our privacy policy." },
      { q: "Can clients pay fees online?", a: "Yes. The AI can send a Razorpay payment link, and you see whether it is paid." },
      { q: "Can it remind clients about due dates?", a: "Yes. Anril Reach sends WhatsApp reminders to clients who agreed to hear from you." },
      COST_FAQ,
    ],
    related: [IND.finance, CRM, PLANS],
  },
];

export function findIndustryPage(slug: string): IndustryPage | undefined {
  return INDUSTRY_PAGES.find((p) => p.slug === slug);
}
