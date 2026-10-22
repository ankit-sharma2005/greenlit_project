import "../styles/progress.css";

export interface ProgressBarProps {
  value: number;
  max?: number;
  label: string;
  /** Show "value / max" next to the label. */
  showValue?: boolean;
}

/** Determinate progress for runs (cases done / total). */
export function ProgressBar({ value, max = 100, label, showValue = true }: ProgressBarProps) {
  const safeMax = max > 0 ? max : 1;
  const clamped = Math.min(Math.max(value, 0), safeMax);
  const percent = (clamped / safeMax) * 100;

  return (
    <div className="progress">
      <div className="progress__header">
        <span>{label}</span>
        {showValue ? (
          <span>
            {clamped} / {safeMax}
          </span>
        ) : null}
      </div>
      <div
        className="progress__track"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={safeMax}
        aria-valuenow={clamped}
        aria-valuetext={`${Math.round(percent)}%`}
      >
        <div className="progress__fill" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
