// Copy and links shared by the /new marketing pages: the approved mockup's copy,
// the Anril AI pamphlet, plain facts about the product, and examples marked as such.

export const SITE_URL = "https://www.anrilaitech.com";
/** The company mailbox (Zoho Mail on anrilaitech.com, live 20 Nov 2026). */
export const CONTACT_EMAIL = "hello@anrilaitech.com";
export const PHONE = { display: "+91 90473 70380", tel: "+919047370380", whatsapp: "https://wa.me/919047370380" } as const;
export const OFFICE = {
  street: "2, Sree Narayana Guru Road, Mission Road, Saibaba Koil",
  city: "Coimbatore", region: "Tamil Nadu", postalCode: "641011", country: "India",
} as const;
/** The office pin on Google Maps (Saibaba Colony, Coimbatore), taken from the shared Maps link. */
export const OFFICE_GEO = { latitude: 11.0259913, longitude: 76.9508703 } as const;
export const MAPS_URL = "https://maps.app.goo.gl/oJCrJKK1X7AuvRTu6";
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
// GSTIN as published on bloommatrix.in ("Bloom Matrix · Registered in India · GSTIN ..."), checked 20 Nov 2026.
// No legal-name suffix, start year or team size is published, so none is shown.
export const MAKER = { name: "Bloom Matrix", href: "https://www.bloommatrix.in", gstin: "33ABEFB3573A1Z0" } as const;
export const DEMO_LABEL = "Book a demo";
/** Every /new page ends with the demo form, so the CTA always stays on the page. */
export const DEMO_HREF = "#demo";
export const SIGN_IN_HREF = "/login";

export type Industry = {
  id: string;
  name: string;
  /** Tile name on the home page. */
  short: string;
  asks: string;
  example: string;
  reply: string;
  outcome: string;
};

// The 10 "Most popular" industries, in sales-priority order (22 Nov 2026 work order). Each has a big card
// on /industries; the first eight are also the home page tiles. Illustrations, marked as examples on the page.
export const INDUSTRIES: readonly Industry[] = [
  {
    id: "education", name: "Education", short: "Education", asks: "Course fees, batch timings, admission dates and campus visits.",
    example: "What are the fees for the weekend batch?",
    reply: "The weekend batch starts next month, on Saturday and Sunday mornings. I can share the fee details and book you a campus visit. Which day suits you?",
    outcome: "Marked hot after asking to visit, and sent to a counsellor to call.",
  },
  {
    id: "coaching", name: "Coaching and training institutes", short: "Coaching", asks: "Batch timings, fees, demo classes and online or offline classes.",
    example: "Is there a weekend batch for NEET coaching? What are the fees?",
    reply: "Yes, we have a weekend batch. I am sharing the fee details and brochure now. Would you like to attend a demo class?",
    outcome: "Marked hot after asking for a demo class, and sent to a counsellor to call.",
  },
  {
    id: "study-abroad", name: "Study abroad", short: "Study abroad", asks: "Countries, courses, test scores, intakes and budgets.",
    example: "I want to do an MS in Canada. Is IELTS 6.5 enough?",
    reply: "6.5 works for many courses. Which intake are you planning, and what is your budget?",
    outcome: "Marked hot after sharing intake and budget, and sent to a counsellor to call.",
  },
  {
    id: "real-estate", name: "Real estate", short: "Real estate", asks: "Prices, floor plans, site visits and home loans.",
    example: "Is the 2 BHK still available? Can I visit on Saturday?",
    reply: "Yes, 2 BHK homes are still available. Site visits on Saturday run from 10 am. Shall I book you a slot?",
    outcome: "Marked hot after booking a visit, and sent to a sales executive to call.",
  },
  {
    id: "healthcare", name: "Healthcare", short: "Healthcare", asks: "Doctor availability, appointment slots, costs and directions.",
    example: "Is the doctor available tomorrow evening?",
    reply: "Yes, the doctor sees patients from 5 pm to 8 pm tomorrow. Would you like me to request a slot?",
    outcome: "Marked hot after asking for a slot, and passed to the front desk to confirm.",
  },
  {
    id: "retail", name: "Retail shops and boutiques", short: "Retail", asks: "Prices, stock, colours, delivery and shop timings.",
    example: "What is the price of this saree? Is green available?",
    reply: "Yes, green is in stock. Here is the price and more photos. Shall I send you the payment link?",
    outcome: "Paid through the payment link in the chat, and the order was created.",
  },
  {
    id: "d2c", name: "D2C brands and online sellers", short: "D2C", asks: "Prices, sizes, delivery times and order status.",
    example: "What is the price? Is size M available?",
    reply: "Yes, size M is in stock. Here is the price. Shall I send the payment link?",
    outcome: "Paid through the payment link in the chat, and the order was created.",
  },
  {
    id: "salons-beauty", name: "Salons, beauty and spas", short: "Salons", asks: "Service prices, appointment slots, bridal packages and offers.",
    example: "How much is the bridal makeup package?",
    reply: "Here are our bridal packages and photos of our work. What is the wedding date?",
    outcome: "Sent to the team as a booking request once the wedding date was shared.",
  },
  {
    id: "jewellery", name: "Jewellery shops", short: "Jewellery", asks: "Designs, weights, today's rate, old gold exchange and store visits.",
    example: "Please send bridal necklace designs. My budget is around 3 lakhs.",
    reply: "Here are some bridal designs in that range. Would you like to visit the store?",
    outcome: "Marked hot after asking to visit, and sent to the store team to call.",
  },
  {
    id: "travel-tours", name: "Travel and tours", short: "Travel", asks: "Packages, itineraries, visas and prices for their dates.",
    example: "How much is a 3-day Kerala package for 4 people?",
    reply: "Here is our Kerala package and itinerary. Which dates are you planning?",
    outcome: "Marked hot after sharing travel dates, and sent to a travel expert to call.",
  },
];

/** The other 10 industries ("More industries" in the menu), as small cards on /industries. */
export const MORE_INDUSTRIES: readonly { id: string; name: string; text: string }[] = [
  { id: "events-weddings", name: "Events and weddings", text: "Shares past work photos and packages, asks date, venue and budget, and sends serious clients to your team." },
  { id: "interiors-construction", name: "Interiors and construction", text: "Shares past work photos, asks size, budget and location, and sends serious clients to your team for a site visit." },
  { id: "gyms-fitness", name: "Gyms and fitness", text: "Answers membership and timing questions, collects trial-visit requests, and follows up when someone goes quiet." },
  { id: "hotels-resorts", name: "Hotels and resorts", text: "Answers room, rate and facility questions from your details, and sends booking requests to your front desk." },
  { id: "automotive", name: "Automotive", text: "Replies to price, EMI and test-drive enquiries, collects model and budget, and sends hot buyers to sales." },
  { id: "restaurants", name: "Restaurants and cloud kitchens", text: "Shares the menu, takes party and catering enquiries, and sends them to your team." },
  { id: "home-services", name: "Home services and repairs", text: "Collects the problem, address and preferred time, and sends the job request to your team." },
  { id: "financial-services", name: "Financial services", text: "Answers common loan and insurance questions, collects basic details, and sends serious leads to advisors." },
  { id: "professional-services", name: "CA, law and consultants", text: "Answers common questions, collects the client’s need, and books a call with your team. Never gives legal or tax advice." },
  { id: "manufacturing", name: "Manufacturing and B2B", text: "Replies to buyer enquiries, collects product, quantity and location, and passes qualified leads to sales." },
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
export type NavGroup = { heading: string; links: readonly NavLink[] };
export type NavItem = NavLink & {
  children?: readonly NavLink[];
  /** A dropdown in headed columns; `children` then holds the same links in one list. */
  groups?: readonly NavGroup[];
  /** A closing line and link under a grouped dropdown. */
  more?: { line: string; link: NavLink };
};

/** Every industry has its own page (see industry-pages.ts). */
export const industryPath = (id: string) => `/industries/${id}`;

/** The Industries menu: two columns, in the sales-priority order of the 22 Nov 2026 work order. Keep in step with industry-pages.ts. */
export const INDUSTRY_GROUPS: readonly NavGroup[] = [
  { heading: "Most popular", links: INDUSTRIES.map((i) => ({ label: i.name, href: industryPath(i.id) })) },
  { heading: "More industries", links: MORE_INDUSTRIES.map((i) => ({ label: i.name, href: industryPath(i.id) })) },
];
export const ALL_INDUSTRIES_LINK: NavLink = { label: "See all industries", href: "/industries" };
export const INDUSTRIES_LINE = "20+ industries, one AI agent";

export const NAV: readonly NavItem[] = [
  {
    label: "Products",
    href: "/product",
    children: [
      { label: "WhatsApp AI agent", href: "/whatsapp-chatbot" },
      { label: "Bulk WhatsApp sender", href: "/bulk-whatsapp-sender" },
      { label: "WhatsApp CRM", href: "/whatsapp-crm" },
      { label: "Telecaller software", href: "/telecaller-software" },
      { label: "Payments and orders", href: "/whatsapp-payments" },
      { label: "Social media and ads", href: "/social-media-ads" },
      { label: "Website development", href: "/website-development" },
      { label: "All features", href: "/product" },
    ],
  },
  { label: "Plans", href: "/pricing" },
  {
    label: "Industries",
    href: "/industries",
    children: INDUSTRY_GROUPS.flatMap((g) => g.links),
    groups: INDUSTRY_GROUPS,
    more: { line: INDUSTRIES_LINE, link: ALL_INDUSTRIES_LINK },
  },
  { label: "Blog", href: "/blog" },
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
