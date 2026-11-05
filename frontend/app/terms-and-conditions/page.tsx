import type { Metadata } from "next";
import Link from "next/link";
import { LegalPageShell, LegalSection, LegalList } from "@/components/legal/LegalPageShell";

export const metadata: Metadata = {
  alternates: { canonical: "/terms-and-conditions" },
  title: "Terms & Conditions",
  description: "The terms and conditions governing access to and use of Anril, a Bloom Matrix product.",
};

export default function TermsAndConditionsPage() {
  return (
    <LegalPageShell title="Terms and Conditions" subtitle="Anril — a Bloom Matrix product" effectiveDate="14 June 2026">
      <p className="text-sm leading-relaxed text-ink-secondary mb-6">
        Welcome to Anril, a cloud-based multi-tenant SaaS platform — a business-focused sales engagement, customer
        communication, automation, lead management, analytics, telecalling, and AI assistance platform operated by
        Bloom Matrix (&ldquo;Bloom Matrix&rdquo;, &ldquo;Company&rdquo;, &ldquo;we&rdquo;, &ldquo;our&rdquo;, or
        &ldquo;us&rdquo;).
      </p>
      <p className="text-sm leading-relaxed text-ink-secondary mb-2">
        By accessing, registering for, or using Anril, you agree to be bound by these Terms and Conditions.
      </p>
      <p className="text-sm leading-relaxed text-ink-secondary mb-10">
        If you do not agree to these Terms, you must not access or use Anril.
      </p>

      <LegalSection title="1. Eligibility">
        <p>Anril is intended solely for business and professional use.</p>
        <p>Users must be at least eighteen (18) years of age and legally capable of entering into binding agreements.</p>
        <p>By using Anril, you represent and warrant that you satisfy these requirements.</p>
      </LegalSection>

      <LegalSection title="2. Services">
        <p>
          Anril is a cloud-based multi-tenant Software-as-a-Service (SaaS) platform that enables businesses to manage
          customer communications, sales engagement, artificial intelligence workflows, telecalling operations,
          business automation, analytics, and integrations with supported third-party communication platforms.
        </p>
        <p>Anril may provide services including:</p>
        <LegalList
          items={[
            "Lead management",
            "CRM functionality",
            "WhatsApp messaging integration",
            "Social messaging integration",
            "AI-powered conversations",
            "Lead scoring",
            "Call management",
            "Telecalling support",
            "Call analytics",
            "Call transcription",
            "Team management",
            "Employee performance monitoring",
            "Reporting and analytics",
            "Payment and booking management",
            "Business automation services",
            "AI-assisted communication services",
          ]}
        />
        <p>
          Bloom Matrix may modify, improve, suspend, discontinue, replace, or remove any feature, functionality,
          integration, or service at any time.
        </p>
      </LegalSection>

      <LegalSection title="3. Account Registration">
        <p>Users may be required to create an account to access Anril.</p>
        <p>You agree to:</p>
        <LegalList
          items={[
            "Provide accurate information",
            "Keep information updated",
            "Maintain account security",
            "Protect login credentials",
            "Restrict unauthorized access",
          ]}
        />
        <p>You are solely responsible for all activities conducted through your account.</p>
      </LegalSection>

      <LegalSection title="4. Customer Data">
        <p>Customers retain ownership of their uploaded data.</p>
        <p>
          Bloom Matrix does not claim ownership of customer business data, customer communications, contact
          databases, message history, call recordings, or connected third-party business assets.
        </p>
        <p>
          By using Anril, customers grant Bloom Matrix a limited, non-exclusive license to process, store, analyze,
          transmit, display, and manage customer data solely for providing and improving the services.
        </p>
        <p>Customers remain solely responsible for:</p>
        <LegalList
          items={[
            "Uploaded contact lists",
            "Message content",
            "Campaign content",
            "Call content",
            "Business information",
            "Customer information",
            "Data accuracy",
            "Data legality",
          ]}
        />
      </LegalSection>

      <LegalSection title="5. Consent and Messaging Responsibilities">
        <p>
          Customers are solely responsible for obtaining all required permissions, authorizations, consents, opt-ins,
          and legal bases required to collect, upload, process, store, and communicate with contacts.
        </p>
        <p>Bloom Matrix does not verify whether contacts have consented to receive communications.</p>
        <p>
          Customers are solely responsible for ensuring that all communications, campaigns, broadcasts, calls,
          messages, and customer interactions conducted through Anril comply with:
        </p>
        <LegalList
          items={[
            "Applicable laws",
            "Data protection laws",
            "Telecommunications laws",
            "Anti-spam laws",
            "WhatsApp Business Platform policies",
            "Meta policies",
            "Instagram policies",
            "Facebook policies",
            "Telegram policies",
            "Telephony provider policies",
            "Business Solution Provider (BSP) requirements, where applicable",
          ]}
        />
        <p>
          Bloom Matrix shall not be responsible for any penalties, restrictions, suspensions, account limitations,
          claims, damages, liabilities, or losses arising from customer messaging practices, customer-provided data,
          contact lists, communications, or violations of third-party platform policies.
        </p>
        <p>
          Customers acknowledge that Anril may automate communications based on customer-configured settings.
          Customers remain solely responsible for reviewing, monitoring, supervising, and controlling the
          communications initiated through their accounts.
        </p>
        <div>
          <p className="font-medium text-ink mb-1.5">Third-Party Account Authorization</p>
          <p>
            Anril may enable customers to connect third-party communication platforms, including the WhatsApp Business
            Platform, through Meta&rsquo;s Embedded Signup or other authorized connection mechanisms.
          </p>
          <p>
            Customers acknowledge that they remain the owners and administrators of their respective Meta Business
            Accounts, WhatsApp Business Accounts, phone numbers, and related assets.
          </p>
          <p>
            By connecting such accounts, customers authorize Bloom Matrix to access and manage the connected assets
            solely for the purpose of providing the services requested through Anril.
          </p>
          <p>
            Customers may revoke such authorization at any time through the applicable Meta or third-party account
            settings, subject to applicable technical limitations.
          </p>
          <p>Bloom Matrix does not acquire ownership of any customer-owned third-party assets.</p>
        </div>
      </LegalSection>

      <LegalSection title="6. Acceptable Use">
        <p>Users shall not:</p>
        <LegalList
          items={[
            "Upload unlawful content",
            "Send spam",
            "Engage in fraudulent activities",
            "Violate privacy rights",
            "Harass, abuse, or threaten individuals",
            "Distribute malware",
            "Attempt unauthorized access",
            "Circumvent security measures",
            "Misuse integrations",
            "Use the platform for unlawful purposes",
          ]}
        />
        <p>Bloom Matrix reserves the right to suspend, restrict, or terminate accounts that violate these requirements.</p>
      </LegalSection>

      <LegalSection title="7. Artificial Intelligence Disclaimer">
        <p>Anril uses artificial intelligence technologies.</p>
        <p>AI-generated outputs:</p>
        <LegalList
          items={[
            "May contain inaccuracies",
            "May be incomplete",
            "May contain errors",
            "May not reflect current information",
            "Should not be considered legal, financial, business, or professional advice",
          ]}
        />
        <p>Users remain solely responsible for reviewing, validating, and evaluating AI-generated outputs before relying upon them.</p>
      </LegalSection>

      <LegalSection title="8. Messaging and Communication Disclaimer">
        <p>Message delivery depends on:</p>
        <LegalList
          items={[
            "Third-party providers",
            "Network availability",
            "Platform restrictions",
            "Recipient availability",
            "External service reliability",
          ]}
        />
        <p>Bloom Matrix does not guarantee:</p>
        <LegalList
          items={[
            "Message delivery",
            "Message visibility",
            "Open rates",
            "Response rates",
            "Conversion rates",
            "Lead quality",
            "Sales outcomes",
            "Business results",
          ]}
        />
      </LegalSection>

      <LegalSection title="9. Fees, Billing, and Payments">
        <p>
          Anril may offer subscription-based pricing, usage-based pricing, feature-based pricing, or a combination of
          such pricing models depending on the services, plans, features, and offerings made available by Bloom
          Matrix.
        </p>
        <p>Fees may include:</p>
        <LegalList
          items={[
            "Subscription fees",
            "Platform access fees",
            "AI usage fees",
            "AI credit purchases",
            "Telephony charges",
            "Messaging charges",
            "Integration fees",
            "Booking-related fees",
            "Additional service fees",
          ]}
        />
        <p>Customers are responsible for all fees, charges, usage costs, taxes, and expenses incurred through their accounts.</p>
        <p>Payment processing may be provided by third-party payment providers, including Razorpay or other payment service providers.</p>
        <p>Bloom Matrix does not store complete payment card information.</p>
      </LegalSection>

      <LegalSection title="10. Refund Policy">
        <p>Unless expressly required by applicable law:</p>
        <LegalList
          items={[
            "Subscription fees are non-refundable.",
            "Platform access fees are non-refundable.",
            "AI credits are non-refundable.",
            "Telephony charges are non-refundable.",
            "Messaging charges are non-refundable.",
            "Integration fees are non-refundable.",
            "Setup fees are non-refundable.",
            "Usage-based charges are non-refundable.",
          ]}
        />
        <p>Once purchased, activated, allocated, consumed, or processed, fees shall not be refunded.</p>
      </LegalSection>

      <LegalSection title="Compliance with Platform Policies">
        <p>
          Customers acknowledge that use of integrated third-party communication platforms remains subject to the
          applicable terms, policies, acceptable use requirements, commerce policies, and messaging policies
          established by such providers.
        </p>
        <p>Suspension or restriction imposed by any third-party platform does not constitute a breach of these Terms by Bloom Matrix.</p>
      </LegalSection>

      <LegalSection title="11. Pricing Changes">
        <p>
          Bloom Matrix reserves the right to modify pricing, subscription plans, usage rates, credit structures,
          service fees, or billing models at any time.
        </p>
        <p>Where reasonably practicable, notice of material pricing changes will be provided before such changes take effect.</p>
      </LegalSection>

      <LegalSection title="12. Connected Third-Party Accounts">
        <p>Customers are responsible for maintaining valid permissions, credentials, and authorizations for all connected third-party services.</p>
        <p>
          Bloom Matrix may lose access to connected services if customers revoke permissions, remove integrations,
          change account ownership, violate third-party policies, or if third-party providers modify their APIs or
          access requirements.
        </p>
        <p>Bloom Matrix shall not be liable for interruptions caused by such actions.</p>
      </LegalSection>

      <LegalSection title="13. Intellectual Property">
        <p>
          All rights, title, and interest in Anril, including software, source code, interfaces, trademarks, branding,
          content, documentation, workflows, designs, and technology, remain the exclusive property of Bloom Matrix
          or its licensors.
        </p>
        <p>These Terms do not transfer ownership rights to users.</p>
      </LegalSection>

      <LegalSection title="14. Third-Party Services">
        <p>Anril may integrate with:</p>
        <LegalList
          items={[
            "WhatsApp Business Platform",
            "Meta services",
            "Facebook Messenger",
            "Instagram",
            "Telegram",
            "Telephony providers",
            "Payment providers",
            "Artificial intelligence providers",
            "Cloud infrastructure providers",
            "Customer-owned Meta Business Accounts",
          ]}
        />
        <p>Bloom Matrix is not responsible for the availability, actions, policies, functionality, performance, or decisions of third-party services.</p>
      </LegalSection>

      <LegalSection title="15. Service Availability">
        <p>The services are provided on an &ldquo;AS IS&rdquo; and &ldquo;AS AVAILABLE&rdquo; basis.</p>
        <p>Bloom Matrix does not guarantee:</p>
        <LegalList
          items={[
            "Uninterrupted service availability",
            "Error-free operation",
            "Continuous access",
            "Specific business outcomes",
            "Compatibility with all third-party services",
          ]}
        />
        <p>
          Service interruptions may occur due to maintenance, updates, third-party failures, security incidents,
          network disruptions, or circumstances beyond our control.
        </p>
      </LegalSection>

      <LegalSection title="16. Suspension and Termination">
        <p>Bloom Matrix reserves the right to suspend, restrict, disable, or terminate accounts for:</p>
        <LegalList
          items={[
            "Spam activities",
            "Policy violations",
            "Non-payment",
            "Fraudulent activities",
            "Unlawful activities",
            "Security risks",
            "Abuse of services",
            "Violations of third-party platform policies",
          ]}
        />
        <p>Access to services may cease immediately upon suspension or termination.</p>
      </LegalSection>

      <LegalSection title="17. Limitation of Liability">
        <p>
          To the maximum extent permitted by law, Bloom Matrix shall not be liable for actions taken by Meta,
          WhatsApp, Instagram, Facebook Messenger, Telegram, telephony providers, payment providers, or other
          third-party platforms, including suspension, restriction, account limitation, policy enforcement, or API
          changes.
        </p>
        <LegalList
          items={[
            "Indirect damages",
            "Consequential damages",
            "Incidental damages",
            "Special damages",
            "Lost profits",
            "Lost revenue",
            "Lost business opportunities",
            "Data loss",
            "Business interruption",
            "Loss of goodwill",
          ]}
        />
        <p>Use of Anril is at the user&rsquo;s sole risk.</p>
      </LegalSection>

      <LegalSection title="18. Indemnification">
        <p>
          Users agree to indemnify, defend, and hold harmless Bloom Matrix, its affiliates, officers, employees,
          contractors, licensors, and partners from and against claims, liabilities, losses, damages, expenses, and
          costs arising from:
        </p>
        <LegalList
          items={[
            "Customer data",
            "Customer communications",
            "Customer conduct",
            "Violations of law",
            "Violations of these Terms",
            "Violations of third-party platform requirements",
          ]}
        />
      </LegalSection>

      <LegalSection title="19. Privacy">
        <p>
          Use of Anril is governed by the{" "}
          <Link href="/privacy-policy" className="text-primary hover:underline">
            Anril Privacy Policy
          </Link>
          , which describes how Bloom Matrix collects, processes, stores, protects, and discloses personal
          information.
        </p>
      </LegalSection>

      <LegalSection title="20. Governing Law and Jurisdiction">
        <p>These Terms shall be governed by and construed in accordance with the laws of India.</p>
        <p>
          Any dispute arising out of or relating to these Terms, Anril, or the use of the services shall be subject to
          the exclusive jurisdiction of the courts located in Coimbatore, Tamil Nadu, India.
        </p>
      </LegalSection>

      <LegalSection title="21. Changes to These Terms">
        <p>Bloom Matrix may update these Terms from time to time.</p>
        <p>Updated versions become effective upon publication.</p>
        <p>Continued use of Anril following publication of updated Terms constitutes acceptance of the revised Terms.</p>
      </LegalSection>

      <LegalSection title="22. Contact Information">
        <LegalList
          items={[
            "Bloom Matrix",
            <>Website: <a href="https://www.anrilaitech.com" className="text-primary hover:underline">https://www.anrilaitech.com</a></>,
          ]}
        />
        <p>Registered Office Address:</p>
        <LegalList items={["352-1, Srinivasapuram Street, Avinashi, Tiruppur, Tamil Nadu – 641654, India"]} />
      </LegalSection>

      <LegalSection title="23. Acceptance">
        <p>
          By accessing, registering for, or using Anril, users acknowledge that they have read, understood, and agreed
          to these Terms and Conditions.
        </p>
      </LegalSection>
    </LegalPageShell>
  );
}
