import { useCallback, useEffect, useState } from "react";

import { Button } from "./Button";
import { ApiError } from "../lib/api";
import { listReviewQueue, saveLabel, type HumanLabel, type ReviewCase } from "../lib/labels";
import "../styles/results.css";

export interface ReviewQueueProps {
  /** Called after a label is saved, so the page can refresh its calibration. */
  onLabelled?: () => void;
}

/**
 * The cases a person should look at: the judge could not score them, was unsure,
 * or a reviewer's label disagrees with it (M7). Nothing here guesses: the judge's
 * own reason and confidence are shown next to the app's answer.
 */
export function ReviewQueue({ onLabelled }: ReviewQueueProps) {
  const [cases, setCases] = useState<ReviewCase[] | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const queue = await listReviewQueue();
      setCases(queue.items);
      setError(null);
    } catch (caught) {
      setCases([]);
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not load the review queue. Check that the API is running.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const label = async (item: ReviewCase, verdict: HumanLabel) => {
    setBusyId(item.run_item_id);
    setError(null);
    try {
      await saveLabel(item.run_item_id, verdict, notes[item.run_item_id] ?? null);
      await load();
      onLabelled?.();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not save the label. Check that you are a reviewer and try again.",
      );
    } finally {
      setBusyId(null);
    }
  };

  if (cases === null) {
    return (
      <p className="card__hint" data-testid="review-loading">
        Loading the review queue…
      </p>
    );
  }

  return (
    <div data-testid="review-queue">
      {error ? (
        <p className="form-error" role="alert" data-testid="review-error">
          {error}
        </p>
      ) : null}

      {cases.length === 0 ? (
        <p className="card__hint" data-testid="review-empty">
          No cases need review: the judge scored every case confidently, and no label disagrees.
        </p>
      ) : (
        <table className="results__table" data-testid="review-table">
          <thead>
            <tr>
              <th scope="col">Case</th>
              <th scope="col">Answer</th>
              <th scope="col">Why it is here</th>
              <th scope="col">Your label</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((item) => (
              <tr key={item.run_item_id} data-testid="review-row">
                <td>
                  <div>{item.input_text}</div>
                  <span className="card__hint">{item.run_name}</span>
                </td>
                <td>{item.output ?? "—"}</td>
                <td>
                  <ul className="review__reasons">
                    {item.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                  {item.judge_reason ? (
                    <span className="card__hint">Judge: {item.judge_reason}</span>
                  ) : null}
                </td>
                <td>
                  <div className="review__actions">
                    <Button
                      variant="secondary"
                      onClick={() => void label(item, "pass")}
                      loading={busyId === item.run_item_id}
                      disabled={busyId !== null}
                      data-testid="review-pass"
                    >
                      Approve
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => void label(item, "fail")}
                      loading={busyId === item.run_item_id}
                      disabled={busyId !== null}
                      data-testid="review-fail"
                    >
                      Reject
                    </Button>
                  </div>
                  <label className="sr-only" htmlFor={`note-${item.run_item_id}`}>
                    Note
                  </label>
                  <input
                    id={`note-${item.run_item_id}`}
                    type="text"
                    placeholder="Optional note"
                    value={notes[item.run_item_id] ?? item.note ?? ""}
                    onChange={(event) =>
                      setNotes((previous) => ({
                        ...previous,
                        [item.run_item_id]: event.target.value,
                      }))
                    }
                    data-testid="review-note"
                  />
                  {item.label ? (
                    <span className="badge badge--neutral" data-testid="review-label">
                      labelled {item.label}
                    </span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
