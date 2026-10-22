import { ComingSoon } from "../components/ComingSoon";

export function TestChatPage() {
  return (
    <>
      <header className="page__header">
        <div>
          <h1>Test Chat</h1>
          <p className="page__description">Talk to the connected app to try it manually.</p>
        </div>
        <ComingSoon detail="Manual chat needs a tested connector, which arrives in M3." />
      </header>

      <section className="empty-state">
        <h2>No connector yet</h2>
        <p>
          Once a connector is configured, this page becomes a chat window to the app under test,
          with retrieval context shown beside each answer.
        </p>
        <div className="empty-state__actions">
          <a href="/">Set up a target</a>
        </div>
      </section>
    </>
  );
}
