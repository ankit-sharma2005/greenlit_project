import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <>
      <header className="page__header">
        <div>
          <h1>Page not found</h1>
          <p className="page__description">
            The page you asked for does not exist. Check the address or go back to New Test.
          </p>
        </div>
      </header>
      <Link to="/">Back to New Test</Link>
    </>
  );
}
