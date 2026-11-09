import { useEffect, useState } from "react";

import { listTemplates } from "../../lib/evaluations";
import type { GaugeThresholds } from "../../lib/chartData";

/**
 * The backend's shipped defaults (`services/criteria.py`: DEFAULT_REVIEW_THRESHOLD 0.60,
 * DEFAULT_GO_THRESHOLD 0.80). Used until the templates arrive, and if they never do, so a
 * chart never blocks on a request.
 */
export const FALLBACK_THRESHOLDS: GaugeThresholds = { review: 0.6, go: 0.8 };

/**
 * The REVIEW and GO thresholds for one criteria profile, from the same templates the
 * Criteria tab reads (`GET /api/v1/evaluations/templates`). A run stores only the profile
 * key, so the thresholds are resolved by that key, falling back to the default template.
 */
export function useCriteriaThresholds(profileKey?: string): GaugeThresholds {
  const [thresholds, setThresholds] = useState<GaugeThresholds>(FALLBACK_THRESHOLDS);

  useEffect(() => {
    let active = true;
    listTemplates()
      .then((response) => {
        if (!active) return;
        const match = profileKey
          ? response.templates.find((template) => template.key === profileKey)
          : undefined;
        const template =
          match ?? response.templates.find((entry) => entry.key === response.default);
        if (template) {
          setThresholds({ review: template.review_threshold, go: template.go_threshold });
        }
      })
      .catch(() => {
        /* Keep the shipped defaults; the chart must still draw. */
      });
    return () => {
      active = false;
    };
  }, [profileKey]);

  return thresholds;
}
