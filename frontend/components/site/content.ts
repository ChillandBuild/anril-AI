// Copy and links shared by the /new marketing pages: the approved mockup's copy,
// the Anril AI pamphlet, plain facts about the product, and examples marked as such.

export const SITE_URL = "https://www.anrilaitech.com";
export const CONTACT_EMAIL = "anrilaitech@gmail.com";
export const PHONE = { display: "+91 90473 70380", tel: "+919047370380", whatsapp: "https://wa.me/919047370380" } as const;
export const OFFICE = {
  street: "2, Sree Narayana Guru Road, Mission Road, Saibaba Koil",
  city: "Coimbatore", region: "Tamil Nadu", postalCode: "641011", country: "India",
} as const;
export const OFFICE_LINE = `${OFFICE.street}, ${OFFICE.city}, ${OFFICE.region} ${OFFICE.postalCode}`;
/** Bloom Matrix's legal registered address (Anril AI's demos are held at the Coimbatore office above). */
export const REGISTERED_OFFICE = "352-1, Srinivasapuram Street, Avinashi, Tiruppur, Tamil Nadu – 641654, India";
export const HOURS = "Monday to Saturday, 10 AM to 6 PM";
export const STARTING_PRICE = "₹999";
export const SOCIAL = [
  { label: "Instagram", href: "https://www.instagram.com/anrilai/" },
  { label: "Facebook", href: "https://www.facebook.com/profile.php?id=61594983276431" },
  { label: "LinkedIn", href: "https://www.linkedin.com/company/143972232/" },
] as const;
/** Anril AI is a product of Bloom Matrix. */
export const MAKER = { name: "Bloom Matrix", href: "https://www.bloommatrix.in" } as const;
export const DEMO_LABEL = "Book a demo";
/** Every /new page ends with the demo form, so the CTA always stays on the page. */
export const DEMO_HREF = "#demo";
export const SIGN_IN_HREF = "/login";

export type Industry = { id: string; name: string; asks: string; example: string; reply: string; outcome: string };

// Illustrations of how a conversation could go in each trade, marked as examples on the page.
export const INDUSTRIES: readonly Industry[] = [
  {
    id: "education", name: "Education", asks: "Course fees, batch timings, admission dates and campus visits.",
    example: "What are the fees for the weekend batch?",
    reply: "The weekend batch starts next month, on Saturday and Sunday mornings. I can share the fee details and book you a campus visit. Which day suits you?",
    outcome: "Marked hot after asking to visit, and sent to a counsellor to call.",
  },
  {
    id: "real-estate", name: "Real estate", asks: "Prices, floor plans, site visits and home loans.",
    example: "Is the 2 BHK still available? Can I visit on Saturday?",
    reply: "Yes, 2 BHK homes are still available. Site visits on Saturday run from 10 am. Shall I book you a slot?",
    outcome: "Marked hot after booking a visit, and sent to a sales executive to call.",
  },
  {
    id: "healthcare", name: "Healthcare", asks: "Doctor availability, appointment slots, costs and directions.",
    example: "Is the doctor available tomorrow evening?",
    reply: "Yes, the doctor sees patients from 5 pm to 8 pm tomorrow. Would you like me to request a slot?",
    outcome: "Marked hot after asking for a slot, and passed to the front desk to confirm.",
  },
  {
    id: "automotive", name: "Automotive", asks: "Test drives, on-road prices, exchange offers and service bookings.",
    example: "What is the on-road price for the automatic?",
    reply: "I can share the on-road price for the automatic in your city. Would you also like to book a test drive?",
    outcome: "Marked hot after asking for a test drive, and sent to a sales executive to call.",
  },
  {
    id: "manufacturing", name: "Manufacturing", asks: "Specifications, minimum order quantities, quotes and delivery times.",
    example: "Can you quote for 500 units, delivered next month?",
    reply: "Yes, we can quote for 500 units. Please share the specification, and our team will send the quote with a delivery date.",
    outcome: "Marked hot after asking for a quote, and sent to the sales team to call.",
  },
  {
    id: "financial-services", name: "Financial services", asks: "Eligibility, interest rates, documents and call backs.",
    example: "Am I eligible for a business loan? Please call me.",
    reply: "I can help with that. What kind of business do you run, and how long has it been trading? A loan advisor will then call you.",
    outcome: "Marked hot after asking for a call back, and sent to a loan advisor.",
  },
];

/** The four modules, as described in the Anril AI pamphlet. */
export type Module = { id: string; name: string; tagline: string; features: readonly (readonly [string, string])[]; flow: string };

export const MODULES: readonly Module[] = [
  {
    id: "reach", name: "Reach", tagline: "Get customers and bring in new leads.",
    features: [
      ["WhatsApp campaigns", "Send offers and updates in bulk."],
      ["Audience segmentation", "Right message, right customers."],
      ["AI conversations", "AI replies to your customers."],
    ],
    flow: "More reach → More enquiries → More leads",
  },
  {
    id: "engage", name: "Engage", tagline: "Start conversations and nurture every lead.",
    features: [
      ["AI conversations", "Answer customer queries instantly."],
      ["Lead scoring", "Spot hot, warm and cold leads."],
      ["Automated follow-ups", "Never miss a potential sale."],
    ],
    flow: "Faster replies → Better engagement → More opportunities",
  },
  {
    id: "calliq", name: "CallIQ", tagline: "Call, understand and follow up.",
    features: [
      ["Chat + call linked", "Pick up where the chat ended."],
      ["Telecaller tracking", "Call timing and productivity."],
      ["AI call analysis", "Call quality and insights."],
    ],
    flow: "Chat → Call → Follow-up",
  },
  {
    id: "commerce", name: "Commerce", tagline: "Get paid, place orders and manage the sale.",
    features: [
      ["WhatsApp ordering", "Customers order in the chat."],
      ["Auto payment links", "Sent without any manual work."],
      ["Orders and invoices", "Order placed, stock updated."],
    ],
    flow: "Order → Pay → Placed → Invoiced",
  },
];

/** Messaging channels named in the pamphlet, plus phone calls through CallIQ. */
export const CHANNELS = ["WhatsApp", "Instagram", "Facebook Messenger", "Telegram", "Web chat", "Phone calls"] as const;

export type NavLink = { label: string; href: string };
export type NavItem = NavLink & { children?: readonly NavLink[] };

/** Industries that have their own page; the rest still live as anchors on /industries. Keep in step with INDUSTRY_PAGES. */
export const INDUSTRY_PAGE_PATHS: Record<string, string> = {
  education: "/industries/education",
  "real-estate": "/industries/real-estate",
  healthcare: "/industries/healthcare",
};

export const NAV: readonly NavItem[] = [
  {
    label: "Products",
    href: "/product",
    children: [
      { label: "WhatsApp AI chatbot", href: "/whatsapp-chatbot" },
      { label: "Bulk WhatsApp sender", href: "/bulk-whatsapp-sender" },
      { label: "WhatsApp CRM", href: "/whatsapp-crm" },
      { label: "Telecaller software", href: "/telecaller-software" },
      { label: "Payments and orders", href: "/whatsapp-payments" },
      { label: "Social media and ads", href: "/social-media-ads" },
      { label: "All features", href: "/product" },
    ],
  },
  { label: "Plans", href: "/pricing" },
  {
    label: "Resources",
    href: "/industries",
    children: [
      ...INDUSTRIES.map((i) => ({ label: i.name, href: INDUSTRY_PAGE_PATHS[i.id] ?? `/industries#${i.id}` })),
      { label: "D2C brands", href: "/industries/d2c" },
    ],
  },
  {
    label: "Company",
    href: "/about",
    children: [
      { label: "About", href: "/about" },
      { label: "Contact", href: "/contact" },
      { label: DEMO_LABEL, href: "/about#demo" },
    ],
  },
];

export const LEGAL_LINKS: readonly NavLink[] = [
  { label: "Privacy policy", href: "/privacy-policy" },
  { label: "Terms and conditions", href: "/terms-and-conditions" },
  { label: "Data deletion", href: "/data-deletion" },
  { label: "Contact", href: "/contact" },
];
