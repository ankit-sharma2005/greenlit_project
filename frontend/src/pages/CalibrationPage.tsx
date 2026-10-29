import { useState } from "react";

import { CalibrationSummary } from "../components/CalibrationSummary";
import { ReviewQueue } from "../components/ReviewQueue";

/**
 * Human review (M7): the cases the judge could not settle, and how well the judge
 * agrees with the people who labelled them. Reviewer or admin only; the API
 * enforces that, so this page is honest about a member's 403 rather than hiding it.
 */
export function CalibrationPage() {
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <>
      <header className="page__header">
        <div>
          <h1>Calibration</h1>
          <p className="page__description">
            Review the cases the judge could not settle, then compare the judge&apos;s calls with
            yours. Agreement beyond chance is reported as Cohen&apos;s kappa.
          </p>
        </div>
      </header>

      <section className="card" data-testid="calibration-page">
        <div className="card__header">
          <h2>Calibration</h2>
        </div>
        <CalibrationSummary refreshKey={refreshKey} />
      </section>

      <section className="card" style={{ marginTop: "var(--space-5)" }}>
        <div className="card__header">
          <h2>Review queue</h2>
        </div>
        <ReviewQueue onLabelled={() => setRefreshKey((key) => key + 1)} />
      </section>
    </>
  );
}
