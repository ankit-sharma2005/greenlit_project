import { useState } from "react";

import { ComingSoon } from "../components/ComingSoon";
import { DatasetsPanel } from "../components/DatasetsPanel";

const SECTIONS = [
  { name: "Providers and models", detail: "Ollama by default, plus OpenAI-compatible providers." },
  { name: "Connectors", detail: "Saved targets and their detected request/response format." },
  { name: "Datasets", detail: "Uploaded and generated test sets, with versions and hashes." },
  { name: "Criteria", detail: "Weights, thresholds and hard gates per metric." },
  { name: "Judge", detail: "The judge model, rubric and confidence handling." },
  { name: "Safety", detail: "Attack set version, safe prompts and hard gates." },
  { name: "Account", detail: "Profile, roles and sessions." },
  { name: "Audit log", detail: "Append-only record of sign-ins and changes." },
  { name: "Preferences", detail: "Theme, previews and defaults for new tests." },
];

const AVAILABLE = new Set(["Datasets"]);

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
