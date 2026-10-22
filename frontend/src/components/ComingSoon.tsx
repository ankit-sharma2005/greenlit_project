export interface ComingSoonProps {
  /** Optional short note shown in the tooltip. */
  detail?: string;
}

/** Marks a feature that is not built yet; nothing here pretends to work. */
export function ComingSoon({ detail }: ComingSoonProps) {
  return (
    <span className="badge badge--soon" title={detail}>
      Coming soon
    </span>
  );
}
