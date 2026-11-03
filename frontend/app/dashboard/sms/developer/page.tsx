import { ApiBuilderCard } from "../ApiBuilderCard";
import { ApiKeyCard } from "../DeveloperTab";

export default function SmsDeveloperPage() {
  return (
    <div className="space-y-4">
      <ApiKeyCard />
      <ApiBuilderCard />
    </div>
  );
}
