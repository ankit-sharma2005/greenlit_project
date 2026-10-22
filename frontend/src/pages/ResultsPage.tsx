import { Link } from "react-router-dom";

import { ComingSoon } from "../components/ComingSoon";

export function ResultsPage() {
  return (
    <>
      <header className="page__header">
        <div>
          <h1>Results</h1>
          <p className="page__description">
            Every run, its verdict, the failed cases and the rule that produced the decision.
          </p>
        </div>
      </header>

      <section className="empty-state">
        <h2>No runs yet</h2>
        <p>
          A run appears here as soon as you start a test from the New Test page. Run history arrives
          with the evaluation engine.
        </p>
        <div className="empty-state__actions">
          <Link to="/">Go to New Test</Link>
          <ComingSoon detail="Run history, comparison and reports arrive in M5–M9." />
        </div>
      </section>
    </>
  );
}
