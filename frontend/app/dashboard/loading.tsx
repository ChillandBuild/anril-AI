// Shown in the content area while a page's server data loads, so the sidebar
// and header stay put. A grey outline of a page instead of a spinner/logo.
export default function DashboardLoading() {
  return (
    <div role="status" aria-label="Loading" className="w-full animate-pulse space-y-5 p-4 md:p-6">
      <div className="h-8 w-1/3 rounded-lg bg-border" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="h-24 rounded-2xl bg-border/60" />
        <div className="h-24 rounded-2xl bg-border/60" />
        <div className="h-24 rounded-2xl bg-border/60" />
      </div>
      <div className="space-y-3">
        <div className="h-12 rounded-xl bg-border/60" />
        <div className="h-12 rounded-xl bg-border/60" />
        <div className="h-12 rounded-xl bg-border/60" />
        <div className="h-12 rounded-xl bg-border/60" />
      </div>
    </div>
  );
}
