import markUrl from "../assets/greenlit-mark.png";
import "../styles/spinner.css";

export type SpinnerSize = "sm" | "md" | "lg" | "xl";

export interface SpinnerProps {
  /** Visual size; `sm` inherits the surrounding text colour (used inside buttons). */
  size?: SpinnerSize;
  /** Accessible label, announced by screen readers and shown for `lg`/`xl` with showLabel. */
  label?: string;
  /** Render the label visibly below the ring. */
  showLabel?: boolean;
  className?: string;
}

const RADIUS = 9.5;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const ARC_LENGTH = CIRCUMFERENCE * 0.28;

/** One spinner used everywhere: page loading, buttons, run progress. */
export function Spinner({
  size = "md",
  label = "Loading",
  showLabel = false,
  className,
}: SpinnerProps) {
  const classes = ["spinner", `spinner--${size}`, className].filter(Boolean).join(" ");

  return (
    <span className={classes} role="status" aria-live="polite">
      <span className="spinner__ringwrap">
        <svg className="spinner__svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <circle
            className="spinner__track"
            cx="12"
            cy="12"
            r={RADIUS}
            fill="none"
            strokeWidth="2.5"
          />
          <circle
            className="spinner__arc"
            cx="12"
            cy="12"
            r={RADIUS}
            fill="none"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeDasharray={`${ARC_LENGTH} ${CIRCUMFERENCE}`}
          />
        </svg>
        {size === "xl" ? (
          <img className="spinner__mark" src={markUrl} alt="" />
        ) : (
          <span className="spinner__dot" aria-hidden="true" />
        )}
      </span>
      {showLabel ? (
        <span className="spinner__label">{label}</span>
      ) : (
        <span className="sr-only">{label}</span>
      )}
    </span>
  );
}
