"use client";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { AiraLoader } from "@/components/AiraLoader";
import { useNavAccess } from "@/components/nav/useNavAccess";
import {
  SETTINGS_GROUP_INFO,
  groupSettingsItems,
  settingsItemsFor,
  type SettingsNavItem,
} from "@/components/settingsNavigation";

const CARD =
  "flex flex-col rounded-2xl border border-border/70 bg-white p-5 shadow-[0_1px_2px_rgba(28,25,23,0.03)]";
const ROW =
  "group flex min-h-11 items-center gap-3 rounded-xl px-2.5 py-2 text-sm font-semibold text-ink hover:bg-surface-low focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary";

function SettingsLink({ item }: { item: SettingsNavItem }) {
  const Icon = item.icon;
  return (
    <Link href={item.href} className={ROW}>
      <Icon size={16} strokeWidth={1.6} className="shrink-0 text-primary" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
      <ChevronRight size={14} strokeWidth={1.6} className="shrink-0 text-ink-muted" aria-hidden="true" />
    </Link>
  );
}

/**
 * The Settings home: one card per group, each with its links. Every link is
 * gated exactly like the page it opens (settingsItemsFor), a card with no
 * visible link is not drawn, and the page itself needs no gate of its own: it
 * only ever shows links the user may open.
 */
export default function SettingsHomePage() {
  const { access, purchasedFeatures, claudeOn, roleLoading } = useNavAccess();
  if (roleLoading) return <AiraLoader inline />;

  const { groups, loose } = groupSettingsItems(settingsItemsFor(access, purchasedFeatures, claudeOn));

  if (groups.length === 0 && loose.length === 0) {
    return (
      <div className="mx-auto max-w-4xl rounded-2xl border border-border-subtle bg-surface-low px-4 py-6 text-center font-body text-sm text-ink-muted">
        There are no settings available for this account.
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 animate-slide-up">
      {groups.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {groups.map(({ group, items }) => {
            const headingId = `settings-card-${group.replace(/\W+/g, "-").toLowerCase()}`;
            return (
            <section key={group} aria-labelledby={headingId} className={CARD}>
              <h2 id={headingId} className="font-display text-base font-extrabold text-ink">
                {group}
              </h2>
              <p className="mt-1 font-body text-sm text-ink-muted">{SETTINGS_GROUP_INFO[group].description}</p>
              <div className="mt-3 flex flex-col gap-0.5 border-t border-border-subtle pt-3">
                {items.map((item) => (
                  <SettingsLink key={item.href} item={item} />
                ))}
              </div>
            </section>
            );
          })}
        </div>
      )}
      {loose.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {loose.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-white px-3.5 text-sm font-semibold text-ink-secondary hover:border-primary/30 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              >
                <Icon size={15} strokeWidth={1.6} className="shrink-0" aria-hidden="true" />
                {item.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
