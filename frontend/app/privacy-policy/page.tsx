import type { Metadata } from "next";
import { LegalPageShell, LegalSection, LegalList } from "@/components/legal/LegalPageShell";

export const metadata: Metadata = {
  alternates: { canonical: "/privacy-policy" },
  title: "Privacy Policy",
  description: "How Bloom Matrix collects, uses, stores, and protects information when businesses access or use Anril.",
};

export default function PrivacyPolicyPage() {
  return (
    <LegalPageShell title="Privacy Policy" subtitle="Anril — a Bloom Matrix product" effectiveDate="14 June 2026">
      <p className="text-sm leading-relaxed text-ink-secondary mb-6">
        Welcome to Anril (&ldquo;Anril&rdquo;), a cloud-based, multi-tenant Software-as-a-Service (SaaS) platform operated by
        Bloom Matrix. Anril enables businesses to manage customer communications, AI-powered workflows, lead management,
        telecalling, analytics, and integrations with supported third-party communication platforms, including the
        WhatsApp Business Platform, Facebook Messenger, Instagram, and Telegram.
      </p>
      <p className="text-sm leading-relaxed text-ink-secondary mb-6">
        This Privacy Policy explains how Bloom Matrix collects, uses, stores, processes, discloses, and protects
        information when businesses access or use Anril and its related services.
      </p>
      <p className="text-sm leading-relaxed text-ink-secondary mb-10">
        By accessing, registering for, or using Anril, you acknowledge that you have read, understood, and agreed to the
        practices described in this Privacy Policy.
      </p>

      <LegalSection title="1. Company Information">
        <p>Anril is operated by:</p>
        <LegalList
          items={[
            "Bloom Matrix",
            <>Website: <a href="https://www.anrilaitech.com" className="text-primary hover:underline">https://www.anrilaitech.com</a></>,
          ]}
        />
        <p>Registered Office Address:</p>
        <LegalList items={["352-1, Srinivasapuram Street, Avinashi, Tiruppur, Tamil Nadu – 641654, India"]} />
      </LegalSection>

      <LegalSection title="2. Scope of this Privacy Policy">
        <p>This Privacy Policy applies to:</p>
        <LegalList
          items={[
            "Anril platform users",
            "Business customers",
            "Customer relationship management activities",
            "Messaging and communication services",
            "AI-powered communication features",
            "Voice calling and call analysis services",
            "Integrated third-party communication channels",
          ]}
        />
        <p>Anril is intended exclusively for business use and is not designed for individuals under the age of 18.</p>
      </LegalSection>

      <LegalSection title="3. Connected Third-Party Business Accounts">
        <p>
          Anril enables businesses to connect third-party communication services, including the WhatsApp Business
          Platform, through Meta&rsquo;s Embedded Signup and other authorized integration mechanisms. Customers remain
          the owners of their respective Meta Business Accounts, WhatsApp Business Accounts, phone numbers, and
          related business assets. Bloom Matrix processes information associated with such connected accounts solely
          for the purpose of providing the services requested by customers. Customers may revoke this authorization at
          any time through the applicable Meta or third-party account settings, subject to applicable technical
          limitations.
        </p>
      </LegalSection>

      <LegalSection title="4. Information We Collect">
        <div>
          <p className="font-medium text-ink mb-1.5">4.1 Account Information</p>
          <p className="mb-1.5">We may collect:</p>
          <LegalList
            items={[
              "Name",
              "Business name",
              "Email address",
              "Login credentials",
              "User preferences",
              "Subscription information",
              "Platform configuration settings",
              "Employee and team member information",
              "Team member contact information",
              "Attendance records",
              "Performance metrics",
              "Call quality assessments",
            ]}
          />
        </div>

        <div>
          <p className="font-medium text-ink mb-1.5">4.2 Lead and Contact Information</p>
          <p className="mb-1.5">Business customers may upload, import, or generate:</p>
          <LegalList
            items={[
              "Names",
              "Phone numbers",
              "Email addresses",
              "Company information",
              "Lead status information",
              "Notes",
              "Customer-provided data",
              "Sales qualification data",
            ]}
          />
        </div>

        <div>
          <p className="font-medium text-ink mb-1.5">4.3 Messaging Information</p>
          <p className="mb-1.5">We may process and store:</p>
          <LegalList
            items={[
              "WhatsApp messages",
              "Instagram conversations",
              "Facebook Messenger conversations",
              "Telegram conversations",
              "Campaign communications",
              "Message delivery records, status events, and read receipts",
              "Template messaging records",
              "AI-generated responses",
              "Conversation history",
            ]}
          />
        </div>

        <div>
          <p className="font-medium text-ink mb-1.5">4.4 Call Information</p>
          <p className="mb-1.5">We may process and store:</p>
          <LegalList
            items={[
              "Call records",
              "Call duration",
              "Call timestamps",
              "Call recordings",
              "Call transcripts",
              "Call analytics",
              "AI-generated summaries",
              "Lead qualification scores",
            ]}
          />
        </div>

        <div>
          <p className="font-medium text-ink mb-1.5">4.5 Technical Information</p>
          <p className="mb-1.5">We may collect:</p>
          <LegalList
            items={[
              "Device information",
              "Browser information",
              "IP address",
              "Usage logs",
              "Diagnostic information",
              "Error logs",
              "Security logs",
            ]}
          />
        </div>

        <div>
          <p className="font-medium text-ink mb-1.5">4.6 Payment Information</p>
          <p className="mb-1.5">
            Where payment-related features are used, we may collect and process information associated with
            transactions, including:
          </p>
          <LegalList
            items={[
              "Customer name",
              "Customer phone number",
              "Payment amount",
              "Payment status",
              "Payment reference numbers",
              "Payment link identifiers",
              "Transaction identifiers",
              "Billing-related information",
            ]}
          />
          <p className="mt-1.5">
            Payment transactions may be processed through third-party payment service providers. Anril does not store
            complete payment card information and relies on authorized payment providers for payment processing.
          </p>
        </div>

        <div>
          <p className="font-medium text-ink mb-1.5">4.7 Connected Third-Party Account Information</p>
          <p className="mb-1.5">We may collect and process information relating to connected third-party business accounts, including:</p>
          <LegalList
            items={[
              "Meta Business Account identifiers",
              "WhatsApp Business Account identifiers",
              "Phone Number IDs",
              "Business asset identifiers",
              "Integration status",
              "Access permissions",
              "Embedded Signup authorization details",
              "Webhook event metadata",
            ]}
          />
        </div>
      </LegalSection>

      <LegalSection title="5. How We Use Information">
        <p>We use information to:</p>
        <LegalList
          items={[
            "Provide platform functionality and deliver messaging services",
            "Facilitate customer communications",
            "Enable AI-powered interactions",
            "Generate lead scores and analyze conversations",
            "Process and record message delivery, status events, and read receipts",
            "Manage templates and campaign communications",
            "Provide customer support",
            "Maintain security and detect fraud or abuse",
            "Comply with legal obligations",
            "Improve platform performance",
            "Develop new features, services, and platform improvements",
            "Where payment features are used, process payments and maintain transaction records",
          ]}
        />
        <p>
          We process information based on customer instructions, to perform our contract with customers, and as
          otherwise described in the &ldquo;Legal Basis for Processing&rdquo; section below.
        </p>
      </LegalSection>

      <LegalSection title="6. How We Use Data Obtained Through WhatsApp, Meta, and Other Connected Platforms">
        <p>
          We use data obtained through the WhatsApp Business Platform, Facebook Messenger, Instagram, and other
          connected platforms solely to provide and support the messaging and related services that customers request
          through Anril.
        </p>
        <p>
          Consistent with the WhatsApp Business Policy and the policies of other connected platforms, we do not use
          data about a person a customer messages through Anril — other than as reasonably necessary to support that
          messaging — for any other purpose. We do not sell such data, and we do not use it for advertising or
          unrelated purposes. All processing of such data is consistent with the Meta Platform Terms, the WhatsApp
          Business Solution Terms, the WhatsApp Business Policy, and the policies of the relevant platforms.
        </p>
      </LegalSection>

      <LegalSection title="7. Artificial Intelligence Processing">
        <p>Anril uses artificial intelligence technologies to assist businesses with:</p>
        <LegalList
          items={[
            "Automated responses",
            "Lead qualification",
            "Lead scoring",
            "Conversation analysis",
            "Call analysis",
            "Call transcription",
            "Customer engagement automation",
            "Performance insights",
          ]}
        />
        <p>
          AI features are intended to assist business users and support operational workflows. AI-generated outputs
          are provided for informational and operational purposes only and may contain inaccuracies. Customers remain
          solely responsible for reviewing and evaluating AI-generated outputs before relying upon them for business,
          legal, financial, compliance, or customer communication purposes.
        </p>
      </LegalSection>

      <LegalSection title="8. Third-Party Services and Integrations">
        <p>
          Anril may access customer-authorized third-party accounts only after customers grant the necessary
          permissions through supported authorization mechanisms. Customers may revoke such authorization at any time
          through the applicable third-party platform. These services include, but are not limited to:
        </p>
        <LegalList
          items={[
            "WhatsApp Business Platform and Meta services",
            "Facebook Messenger",
            "Instagram",
            "Telegram",
            "Telephony service providers",
            "Payment service providers (e.g., Razorpay)",
            "Cloud infrastructure providers",
            "Artificial intelligence service providers",
          ]}
        />
      </LegalSection>

      <LegalSection title="9. Customer Responsibilities">
        <p>Customers remain responsible for:</p>
        <LegalList
          items={[
            "Maintaining valid permissions for all connected third-party services and ensuring continued compliance with the applicable policies of those providers",
            "Obtaining any permissions, authorizations, consents, or legal basis required to collect and process contact information",
            "Ensuring compliance with applicable laws and regulations",
            "Ensuring uploaded data is lawful, accurate, and properly obtained",
          ]}
        />
        <p>
          Anril does not independently verify whether uploaded contacts have consented to receive communications.
          Customers are responsible for ensuring that all communications, campaigns, calls, messages, and customer
          interactions conducted through Anril comply with applicable laws, regulations, industry requirements, and
          third-party platform policies, including but not limited to WhatsApp Business Platform policies, Meta
          policies, telephony provider requirements, and messaging service provider rules.
        </p>
        <p>
          Customers acknowledge that Anril acts solely as a technology platform and does not determine, monitor,
          validate, or guarantee the legality, accuracy, appropriateness, or compliance of customer-provided data,
          contact lists, communications, or business activities. Delivery of messages, calls, and notifications may
          depend on third-party service providers, network availability, recipient availability, and platform
          restrictions, and Anril does not guarantee message delivery, response rates, engagement, conversion rates, or
          communication outcomes.
        </p>
      </LegalSection>

      <LegalSection title="10. Data Sharing and Disclosure">
        <p>Bloom Matrix does not sell customer business data or customer-owned communication data to third parties.</p>
        <p>We may share information:</p>
        <LegalList
          items={[
            "With service providers supporting platform operations",
            "With messaging providers",
            "With telephony providers",
            "With cloud hosting providers",
            "With analytics providers",
            "When required by law",
            "To enforce our rights",
            "To protect platform security",
            "In connection with mergers, acquisitions, or corporate restructuring",
          ]}
        />
      </LegalSection>

      <LegalSection title="11. Third-Party Platform Processing">
        <p>
          Certain information may be processed by third-party platforms, including Meta, the WhatsApp Business
          Platform, Instagram, Facebook Messenger, Telegram, telephony providers, payment providers, cloud
          infrastructure providers, and artificial intelligence providers, when customers choose to connect such
          services. Processing by such providers remains subject to their respective privacy policies and terms.
        </p>
      </LegalSection>

      <LegalSection title="12. Legal Basis for Processing">
        <p>Bloom Matrix processes information where necessary to:</p>
        <LegalList
          items={[
            "Perform contractual obligations",
            "Provide requested services",
            "Comply with legal obligations",
            "Protect legitimate business interests",
            "Operate and secure the platform",
            "Process information based on customer instructions or applicable consent, where required by law",
          ]}
        />
      </LegalSection>

      <LegalSection title="13. Data Retention">
        <p>
          We retain information for as long as necessary to provide services and operate customer accounts. Unless
          otherwise required by law, information is retained until account deletion or termination, after which it is
          deleted or anonymized within a commercially reasonable period. Certain information may be retained for
          legal, compliance, security, auditing, dispute resolution, or legitimate business purposes.
        </p>
      </LegalSection>

      <LegalSection title="14. Data Deletion and How to Request It">
        <p>You may request deletion of your personal data at any time. This right is available to all users who can access Anril.</p>
        <p>
          To request deletion, send a written request marked &ldquo;Data Deletion Request&rdquo; to our registered
          office address (listed under Contact Information), together with enough information for us to identify the
          relevant account or data. We will verify the request and delete the relevant personal data without undue
          delay, and in any event within thirty (30) days, unless we are legally required or permitted to retain it
          (for example, for legal, tax, security, or dispute-resolution purposes).
        </p>
        <p>
          For data associated with connected Meta, WhatsApp Business, Facebook, Instagram, or Telegram accounts, you
          may also revoke Anril&rsquo;s access at any time through the applicable third-party platform&rsquo;s
          settings. Certain data controlled directly by those platforms can only be deleted through the platform
          itself.
        </p>
        <p>
          Where a business customer has uploaded end-customer contact or communication data, that customer acts as
          the controller of such data. End-customers may direct deletion requests to the relevant business customer,
          and Bloom Matrix will assist that customer in fulfilling such requests. Upon termination or closure of a
          customer account, we will delete or anonymize the associated personal data within a commercially reasonable
          period, subject to legal retention requirements.
        </p>
      </LegalSection>

      <LegalSection title="15. Data Security">
        <p>
          Bloom Matrix implements reasonable technical, organizational, and administrative safeguards designed to
          protect information against unauthorized access, unauthorized disclosure, misuse, loss, alteration, and
          destruction.
        </p>
        <p>
          Access to customer information is restricted to authorized personnel and authorized service providers who
          require such access for legitimate business purposes and who are subject to appropriate contractual,
          confidentiality, and security obligations. We maintain safeguards that meet or exceed applicable industry
          standards given the sensitivity of the information processed.
        </p>
        <p>
          We regularly review and update our security practices to help protect the confidentiality, integrity, and
          availability of information processed through Anril. However, no system, network, or method of electronic
          transmission or storage can guarantee absolute security, and Bloom Matrix cannot guarantee that information
          will be completely secure against all risks or unauthorized access.
        </p>
      </LegalSection>

      <LegalSection title="16. International Data Transfers">
        <p>
          Anril primarily operates from India. Certain service providers, cloud infrastructure providers, communication
          providers, artificial intelligence providers, and technology partners may process, store, or access
          information outside India. Where personal data is transferred outside India, Bloom Matrix will take
          reasonable measures designed to protect such information in accordance with applicable laws, industry
          standards, contractual safeguards, and the Digital Personal Data Protection Act, 2023 (DPDP Act), where
          applicable.
        </p>
      </LegalSection>

      <LegalSection title="17. Your Rights">
        <p>
          Subject to applicable laws, including the Digital Personal Data Protection Act, 2023 (DPDP Act), where
          applicable, users may have the right to:
        </p>
        <LegalList
          items={[
            "Access personal information",
            "Correct inaccurate or incomplete information",
            "Request deletion of information, subject to applicable legal, contractual, operational, and regulatory obligations",
            "Withdraw consent where applicable",
            "Restrict or object to processing where permitted by law",
            "Request copies of certain information",
            "Request information regarding data associated with connected third-party integrations, subject to applicable legal and technical limitations",
            "Nominate another individual to exercise these rights in the event of death or incapacity, where required by the DPDP Act",
          ]}
        />
        <p>
          Requests may be submitted in writing to our registered office address listed under Contact Information.
          Bloom Matrix will review and respond in accordance with applicable laws and our legal, contractual,
          operational, security, and regulatory obligations. Certain requests may be limited where Bloom Matrix is
          legally required or technically unable to disclose, modify, or delete information, including information
          controlled by connected third-party platforms. If you are not satisfied with our response, you may have the
          right to complain to the relevant data protection authority, including the Data Protection Board of India,
          where applicable.
        </p>
      </LegalSection>

      <LegalSection title="18. Children's Privacy">
        <p>
          Anril is intended exclusively for business users and is not directed toward individuals under the age of 18.
          We do not knowingly collect information from children. If we become aware that we have collected
          information from a child, we will delete it.
        </p>
      </LegalSection>

      <LegalSection title="19. Changes to this Privacy Policy">
        <p>
          We may update this Privacy Policy from time to time. Updated versions become effective upon publication.
          Continued use of Anril following publication of an updated Privacy Policy constitutes acceptance of the
          revised version.
        </p>
      </LegalSection>

      <LegalSection title="20. Contact Information">
        <p>For privacy-related questions, concerns, requests, or notices, please contact:</p>
        <LegalList
          items={[
            "Bloom Matrix",
            <>Website: <a href="https://www.anrilaitech.com" className="text-primary hover:underline">https://www.anrilaitech.com</a></>,
          ]}
        />
        <p>Registered Office Address:</p>
        <LegalList items={["352-1, Srinivasapuram Street, Avinashi, Tiruppur, Tamil Nadu – 641654, India"]} />
      </LegalSection>

      <LegalSection title="21. Acceptance">
        <p>By accessing or using Anril, users acknowledge that they have read, understood, and agreed to this Privacy Policy.</p>
      </LegalSection>
    </LegalPageShell>
  );
}
