import { ComingSoon } from "../components/ComingSoon";

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

export function SettingsPage() {
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

      <section className="card" aria-labelledby="settings-sections">
        <div className="card__header">
          <h2 id="settings-sections">Sections</h2>
          <ComingSoon detail="Settings tabs arrive with their features, starting in M2." />
        </div>
        <ul className="plain-list">
          {SECTIONS.map((section) => (
            <li key={section.name} className="plain-list__item">
              <div>
                <strong>{section.name}</strong>
                <p className="card__hint">{section.detail}</p>
              </div>
              <ComingSoon />
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
