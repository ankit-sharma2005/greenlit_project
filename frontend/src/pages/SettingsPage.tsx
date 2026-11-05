import { useState } from "react";

import { AccountPanel } from "../components/AccountPanel";
import { AuditPanel } from "../components/AuditPanel";
import { ComingSoon } from "../components/ComingSoon";
import { CriteriaPanel } from "../components/CriteriaPanel";
import { DatasetsPanel } from "../components/DatasetsPanel";
import { JudgePanel } from "../components/JudgePanel";
import { PreferencesPanel } from "../components/PreferencesPanel";
import { ProvidersPanel } from "../components/ProvidersPanel";
import { SafetyPanel } from "../components/SafetyPanel";

const SECTIONS = [
  { name: "Providers and models", detail: "Ollama by default, plus OpenAI-compatible providers." },
  { name: "Connectors", detail: "Saved targets and their detected request/response format." },
  { name: "Datasets", detail: "Uploaded and generated test sets, with versions and hashes." },
  { name: "Criteria", detail: "Weights, thresholds and hard gates per metric." },
  { name: "Judge", detail: "The judge model, rubric and confidence handling." },
  { name: "Safety", detail: "Attack set version, safe prompts and hard gates." },
  { name: "Account", detail: "Your profile, display name and session." },
  { name: "Audit log", detail: "Append-only record of sign-ins and changes." },
  { name: "Preferences", detail: "Appearance: dark, light or follow the system." },
];

// Only tabs with a working panel are listed here; everything else keeps "soon".
const AVAILABLE = new Set([
  "Datasets",
  "Providers and models",
  "Criteria",
  "Judge",
  "Safety",
  "Account",
  "Preferences",
  "Audit log",
]);

export function SettingsPage() {
  const [active, setActive] = useState("Datasets");
  const current = SECTIONS.find((section) => section.name === active) ?? {
    name: active,
    detail: "",
  };

  return (
    <>
      <header className="page__header">
        <div>
          <h1>Settings</h1>
          <p className="page__description">
            Everything technical lives here, with good defaults. A first test never needs this page.
          </p>
        </div>
      </header>

      <div className="settings__layout">
        <nav className="settings__nav" aria-label="Settings sections">
          {SECTIONS.map((section) => (
            <button
              key={section.name}
              type="button"
              aria-current={active === section.name}
              data-testid={`settings-tab-${section.name.toLowerCase().replace(/[^a-z]+/g, "-")}`}
              onClick={() => setActive(section.name)}
            >
              {section.name}
              {!AVAILABLE.has(section.name) && (
                <>
                  {" "}
                  <span className="badge badge--neutral">soon</span>
                </>
              )}
            </button>
          ))}
        </nav>

        <div className="settings__main">
          {active === "Datasets" ? (
            <>
              <h2>Datasets</h2>
              <p className="page__description" style={{ marginBottom: "var(--space-4)" }}>
                Upload a file, check the detected columns, generate extra cases with the LLM and
                approve the versions runs will use.
              </p>
              <DatasetsPanel />
            </>
          ) : active === "Providers and models" ? (
            <>
              <h2>Providers and models</h2>
              <p className="page__description" style={{ marginBottom: "var(--space-4)" }}>
                Ollama by default, plus OpenAI-compatible providers. Test connections and track
                health.
              </p>
              <ProvidersPanel />
            </>
          ) : active === "Judge" ? (
            <>
              <h2>Judge</h2>
              <p className="page__description" style={{ marginBottom: "var(--space-4)" }}>
                The model that grades your answers against the expected ones, with the rubric and
                confidence handling that decide when a verdict needs a human.
              </p>
              <JudgePanel />
            </>
          ) : active === "Criteria" ? (
            <>
              <h2>Criteria</h2>
              <p className="page__description" style={{ marginBottom: "var(--space-4)" }}>
                How a run is scored and how its verdict is decided: the weights, the hard gates and
                the two thresholds, straight from the decision engine.
              </p>
              <CriteriaPanel />
            </>
          ) : active === "Safety" ? (
            <>
              <h2>Safety</h2>
              <p className="page__description" style={{ marginBottom: "var(--space-4)" }}>
                The built-in attack set and harmless prompts every Safety run sends, with the rule
                that turns a leak into a hard NO-GO.
              </p>
              <SafetyPanel />
            </>
          ) : active === "Account" ? (
            <AccountPanel />
          ) : active === "Preferences" ? (
            <PreferencesPanel />
          ) : active === "Audit log" ? (
            <>
              <h2>Audit log</h2>
              <p className="page__description" style={{ marginBottom: "var(--space-4)" }}>
                Append-only record of sign-ins and changes. Admins only.
              </p>
              <AuditPanel />
            </>
          ) : (
            <section className="card" aria-labelledby="settings-current">
              <div className="card__header">
                <h2 id="settings-current">{current.name}</h2>
                <ComingSoon
                  detail={`The ${current.name.toLowerCase()} tab ships with its milestone.`}
                />
              </div>
              <p className="card__hint">{current.detail}</p>
            </section>
          )}
        </div>
      </div>
    </>
  );
}
