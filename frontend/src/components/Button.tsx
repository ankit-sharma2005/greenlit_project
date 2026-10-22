import { useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

import { Spinner } from "./Spinner";
import "../styles/button.css";

export type ButtonVariant = "primary" | "secondary" | "ghost";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "md" | "lg";
  /** Show the spinner and block interaction while an async action runs. */
  loading?: boolean;
  /** Accessible label while loading; defaults to the button's text. */
  loadingLabel?: string;
  children: ReactNode;
}

/** How long before a loading button announces "Still working…". */
export const SLOW_ACTION_MS = 10_000;

/**
 * Button that cannot be clicked twice while loading. The label keeps its space so the
 * button does not jump when the spinner appears.
 */
export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  loadingLabel,
  disabled,
  children,
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  const [isSlow, setIsSlow] = useState(false);

  useEffect(() => {
    if (!loading) {
      setIsSlow(false);
      return;
    }
    const timer = window.setTimeout(() => setIsSlow(true), SLOW_ACTION_MS);
    return () => window.clearTimeout(timer);
  }, [loading]);

  const classes = ["btn", `btn--${variant}`, size === "lg" ? "btn--lg" : "", className]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      {...rest}
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      aria-label={loading && isSlow ? "Still working…" : rest["aria-label"]}
      title={loading && isSlow ? "Still working…" : rest.title}
      data-slow={isSlow || undefined}
    >
      <span className="btn__label" data-hidden={loading || undefined}>
        {children}
      </span>
      {loading ? (
        <span className="btn__spinner">
          <Spinner size="sm" label={loadingLabel ?? "Working…"} />
        </span>
      ) : null}
    </button>
  );
}
