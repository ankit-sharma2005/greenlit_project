import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/authContext";
import { Brand } from "../components/Brand";
import { Button } from "../components/Button";
import { ApiError } from "../lib/api";
import "../styles/auth.css";

const MIN_PASSWORD_LENGTH = 10;

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!name.trim() || !email.trim()) {
      setError("Enter your name and email.");
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Use at least ${MIN_PASSWORD_LENGTH} characters for your password.`);
      return;
    }

    setSubmitting(true);
    try {
      await register({ name: name.trim(), email: email.trim(), password });
      navigate("/", { replace: true });
    } catch (caught) {
      if (caught instanceof ApiError && caught.fields.length > 0) {
        setError(caught.fields.map((field) => field.message).join(" "));
      } else {
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Could not create the account. Check your connection and try again.",
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <main className="auth-card">
        <Brand />
        <header>
          <h1>Create your account</h1>
          <p className="page__description">
            The first account becomes the admin. Everyone else joins as a member.
          </p>
        </header>

        <form className="auth-form" onSubmit={handleSubmit} noValidate>
          <div className="form-field">
            <label htmlFor="register-name">Name</label>
            <input
              id="register-name"
              type="text"
              autoComplete="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </div>

          <div className="form-field">
            <label htmlFor="register-email">Email</label>
            <input
              id="register-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </div>

          <div className="form-field">
            <label htmlFor="register-password">Password</label>
            <input
              id="register-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              aria-describedby="register-password-hint"
              required
            />
            <p id="register-password-hint" className="form-hint">
              At least {MIN_PASSWORD_LENGTH} characters.
            </p>
          </div>

          {error ? (
            <p className="form-error" role="alert">
              {error}
            </p>
          ) : null}

          <Button type="submit" loading={submitting} loadingLabel="Creating the account">
            Create account
          </Button>
        </form>

        <p className="auth-footer">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </main>
    </div>
  );
}
