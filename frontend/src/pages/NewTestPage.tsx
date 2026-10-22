import { Button } from "../components/Button";
import { ComingSoon } from "../components/ComingSoon";

/** Home: one page where a first-time user points GreenLit at an app and gets a verdict. */
export function NewTestPage() {
  return (
    <>
      <header className="page__header">
        <div>
          <h1>New Test</h1>
          <p className="page__description">
            Point GreenLit at your LLM app and get one decision — GO, REVIEW or NO-GO — with the
            evidence behind it.
          </p>
        </div>
      </header>

      <section className="card" aria-labelledby="target-heading">
        <div className="card__header">
          <h2 id="target-heading">What should GreenLit test?</h2>
          <ComingSoon detail="The endpoint, prompt-app and upload connectors arrive in M3." />
        </div>
        <p className="card__hint">
          Three entry points will be available here: an HTTP endpoint, a prompt app (system prompt
          plus model), or uploaded outputs (CSV or JSON). Everything else stays in Settings →
          Advanced.
        </p>
        <div style={{ marginTop: "var(--space-5)" }}>
          <Button variant="primary" size="lg" disabled title="Connection setup arrives in M3.">
            Start test
          </Button>
        </div>
      </section>

      <section className="card" aria-labelledby="demo-heading">
        <div className="card__header">
          <h2 id="demo-heading">See it working first</h2>
          <ComingSoon detail="The built-in demo app ships in M10." />
        </div>
        <p className="card__hint">
          The demo runs a sample helpdesk app twice — a healthy version and a broken one — so you
          can see a GO and a NO-GO report without configuring anything.
        </p>
        <div style={{ marginTop: "var(--space-5)" }}>
          <Button variant="secondary" disabled title="Demo data ships in M10.">
            Try the demo
          </Button>
        </div>
      </section>
    </>
  );
}
