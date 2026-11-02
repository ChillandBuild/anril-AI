import { AiraLoader } from "@/components/AiraLoader";

// Shown in the content area while a page's server data loads, so the sidebar
// and header stay put instead of the whole screen flashing to a loader.
export default function DashboardLoading() {
  return <AiraLoader inline />;
}
