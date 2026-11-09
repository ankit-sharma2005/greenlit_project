import { useState } from "react";

import { DraftGeneratorPanel } from "./DraftGeneratorPanel";
import { DraftReview } from "./DraftReview";
import type { DatasetDraft } from "../lib/drafts";

/**
 * Settings → Datasets: the generator form and the review table for the draft it just
 * produced. The draft is held here so the table appears as soon as generation finishes.
 */
export function DatasetDrafting() {
  const [draft, setDraft] = useState<DatasetDraft | null>(null);

  return (
    <>
      <DraftGeneratorPanel onCreated={setDraft} />
      <DraftReview draft={draft} onChange={setDraft} />
    </>
  );
}
