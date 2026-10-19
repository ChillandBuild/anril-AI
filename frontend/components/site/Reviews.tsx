import ui from "./site.module.css";
import { Kicker } from "./primitives";
import s from "./Reviews.module.css";

type Review = { title: string; topic: string; quote: string; name: string; role: string; business: string };

// Real customer reviews, all five stars, worded as the customers approved. Names are
// changed and logos left out at the customers' request.
const REVIEWS: readonly Review[] = [
  {
    title: "Never miss an enquiry again",
    topic: "Enquiry management",
    quote:
      "Anril AI has made managing customer enquiries significantly easier for our team. Earlier, keeping track of incoming messages and responding on time was a constant challenge. Now, we can handle enquiries more efficiently and ensure potential customers receive timely attention. It has helped us deliver a more consistent and professional customer experience.",
    name: "Ramesh.",
    role: "Business Owner",
    business: "Customer-facing business",
  },
  {
    title: "A smarter way to prioritise leads",
    topic: "AI lead scoring",
    quote:
      "What we appreciate most about Anril AI is the clarity it brings to our lead management process. Instead of treating every enquiry the same way, our team can focus on the prospects who need attention first. This has helped us organize follow-ups better, use our time more effectively, and bring greater structure to our sales process.",
    name: "Sneha.",
    role: "Sales Manager",
    business: "Sales-driven business",
  },
  {
    title: "All our customer conversations, in one place",
    topic: "Omnichannel communication",
    quote:
      "Managing enquiries across multiple platforms used to make it difficult to maintain a clear view of customer conversations. Anril AI brings greater organization to the process by helping us manage interactions in one place. Our team can follow conversations more easily, coordinate follow-ups, and provide a more seamless experience across customer touchpoints.",
    name: "Daniel.",
    role: "Operations Manager",
    business: "Multi-channel business",
  },
  {
    title: "Better visibility into team performance",
    topic: "AI call scoring",
    quote:
      "Managing call quality becomes much easier with Anril AI. The call scoring feature helps us identify what our team is doing well and where conversations could be improved. Rather than relying entirely on manual call reviews, we have a more structured way to evaluate performance, guide our telecallers, and continuously improve the quality of customer interactions.",
    name: "Arjun.",
    role: "Sales Head",
    business: "Team management",
  },
  {
    title: "More meaningful customer conversations",
    topic: "Telecaller support",
    quote:
      "Anril AI gives our telecalling team better context before they speak with a customer. Having the previous conversation available makes follow-ups feel more informed and relevant, rather than repetitive. Our team can spend less time collecting the same information and more time understanding customer needs and moving conversations forward.",
    name: "Kavya.",
    role: "Telecalling Team Lead",
    business: "Customer acquisition",
  },
  {
    title: "A valuable addition to our sales process",
    topic: "Overall business impact",
    quote:
      "Anril AI has brought a more systematic approach to how we manage enquiries, follow up with prospects, and evaluate our sales conversations. What stands out is the way it brings multiple parts of the customer engagement process together. For a business looking to improve sales coordination and manage leads more effectively, Anril AI is a solution worth considering.",
    name: "Maria.",
    role: "Founder",
    business: "Growing business",
  },
];

function Stars() {
  return (
    <span className={s.stars} role="img" aria-label="Rated 5 out of 5">
      {Array.from({ length: 5 }, (_, i) => (
        <svg key={i} viewBox="0 0 20 20" width="16" height="16" aria-hidden="true" focusable="false">
          <path d="M10 1.5l2.6 5.5 6 .8-4.4 4.1 1.1 5.9L10 15l-5.3 2.8 1.1-5.9L1.4 7.8l6-.8z" fill="currentColor" />
        </svg>
      ))}
    </span>
  );
}

function Card({ r, lead = false }: { r: Review; lead?: boolean }) {
  return (
    <figure className={lead ? `${s.card} ${s.lead}` : s.card}>
      <Stars />
      <span className={s.topic}>{r.topic}</span>
      {lead ? <h3 className={s.leadTitle}>{r.title}</h3> : <h3 className={s.title}>{r.title}</h3>}
      <blockquote className={lead ? `${s.quote} ${s.leadQuote}` : s.quote}>
        <p>&ldquo;{r.quote}&rdquo;</p>
      </blockquote>
      <figcaption className={s.who}>
        <b>{r.name}</b>
        <span>
          {r.role} · {r.business}
        </span>
      </figcaption>
    </figure>
  );
}

/** One review set large beside a 2 x 2 grid of four more, with the sixth under the lead so both sides finish together. */
export function Reviews() {
  // The layout is built for exactly six reviews: one lead, four in the grid, one under the lead.
  const [first, ...others] = REVIEWS;
  const last = others[others.length - 1];
  const middle = others.slice(0, -1);
  return (
    <section className={s.reviews} id="reviews" aria-labelledby="rev-h">
      <div className={ui.band}>
        <Kicker>Customers</Kicker>
        <h2 className={ui.secH} id="rev-h">What our customers say</h2>
        <p className={ui.lede}>From businesses in India and overseas. Every one of them rated Anril AI five stars.</p>
      </div>
      <div className={s.layout}>
        <div className={s.leadCol}>
          <div className={s.leadWrap} data-reveal>
            <Card r={first} lead />
          </div>
          <div className={s.under} data-reveal>
            <Card r={last} />
          </div>
        </div>
        <ul className={s.masonry}>
          {middle.map((r, i) => (
            <li key={r.title} data-reveal style={{ "--rd": `${i * 80}ms` } as React.CSSProperties}>
              <Card r={r} />
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
