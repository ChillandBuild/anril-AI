import {
  Code2,
  Home,
  KeyRound,
  Library,
  Activity,
  MessageCircle,
  Settings,
  Share2,
  Sparkles,
  Upload,
  UserRound,
  type LucideIcon,
} from "lucide-react";

export type AgentsNavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shown on the header bar while this page is open. */
  description: string;
  /** Listed but not built yet: shown greyed with a "Later" tag, no link. */
  later?: boolean;
};

export const AGENTS_NAV: readonly { title: string | null; items: readonly AgentsNavItem[] }[] = [
  {
    title: null,
    items: [
      { href: "/dashboard/agents", label: "Overview", icon: Home, description: "Put a character on your site and see how it is doing." },
      {
        href: "/dashboard/agents/playground",
        label: "Playground",
        icon: MessageCircle,
        description: "Chat with a character as a test person, or search what it would be handed. Test chats never mix with real customers.",
      },
    ],
  },
  {
    title: "Characters",
    items: [
      { href: "/dashboard/agents/characters", label: "Characters", icon: UserRound, description: "Each character has its own persona, memory and knowledge. Click one to edit it." },
      { href: "/dashboard/agents/memories", label: "Memories", icon: Share2, description: "What each character has learned about each person." },
      { href: "/dashboard/agents/knowledge", label: "Upload", icon: Upload, description: "Add files for your characters. Every page is read, and you can see which ones were not." },
      { href: "/dashboard/agents/collections", label: "Collections", icon: Library, description: "Groups of files. A character reads one collection." },
    ],
  },
  {
    title: "Developer",
    items: [
      { href: "/dashboard/agents/keys", label: "API Keys", icon: KeyRound, description: "Secret keys let your server talk to your characters." },
      { href: "/dashboard/agents/install", label: "Install", icon: Code2, description: "Put a character on your website or in your app." },
      { href: "/dashboard/agents/requests", label: "Requests", icon: Activity, description: "Every call to your characters. Message text is never stored." },
      { href: "/dashboard/agents/insights", label: "User Insights", icon: Sparkles, description: "", later: true },
      { href: "/dashboard/agents/settings", label: "Settings", icon: Settings, description: "Memory settings for your whole business." },
    ],
  },
];

const ALL_ITEMS = AGENTS_NAV.flatMap((section) => section.items);

/** Overview matches only its own path; every other item also owns its sub-pages. */
export function isAgentsItemActive(item: AgentsNavItem, pathname: string): boolean {
  if (item.href === "/dashboard/agents") return pathname === item.href;
  return pathname === item.href || pathname.startsWith(item.href + "/");
}

export function agentsRouteMeta(pathname: string): { title: string; description: string } | null {
  const item = ALL_ITEMS.find((i) => !i.later && isAgentsItemActive(i, pathname));
  if (!item) return null;
  return { title: item.label, description: item.description };
}
