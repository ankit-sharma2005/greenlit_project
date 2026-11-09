import { useEffect, useState } from "react";

import { getRunItems } from "../lib/runs";

/**
 * The cases whose answer contained text addressed to the judge.
 *
 * The flag is derived by the server from the stored answer. It is not a verdict: it changes
 * no score, no metric and no decision. This notice puts it where a person reads the run, so
 * "the answer told the judge to give it 1.0" is visible instead of buried in the JSON.
 */
export function JudgeManipulationNotice({ runId }: { runId: string }) {
  const [rows, setRows] = useState<number[]>([]);

  useEffect(() => {
    let active = true;
    getRunItems(runId)
      .then((response) => {
        if (!active) return;
        setRows(
          response.items
            .filter((item) => item.possible_judge_manipulation)
            .map((item) => item.row_index),
        );
      })
      .catch(() => {
        /* Items unreadable: say nothing rather than guess. */
        if (active) setRows([]);
      });
    return () => {
      active = false;
    };
  }, [runId]);

  if (rows.length === 0) return null;

  return (
    <p className="notice" role="status" data-testid="possible-judge-manipulation">
      <strong>Text addressed to the judge.</strong>{" "}
      {rows.length === 1 ? "Case" : "Cases"} {rows.join(", ")} answered with words meant for the
      judge rather than for the question. No score or verdict was changed by it; read the case
      yourself.
    </p>
  );
}
