import { MetaAdsClient } from "../../MetaAdsClient";

export default function InstantFormPage({ params }: { params: { formId: string } }) {
  return <MetaAdsClient view="forms" formId={params.formId} />;
}
