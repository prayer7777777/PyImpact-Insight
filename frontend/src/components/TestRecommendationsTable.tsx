import type { TestSuggestionItem, WarningMessage } from "../api/types";
import { StatusBadge } from "./StatusBadge";

interface TestRecommendationsTableProps {
  recommendations: TestSuggestionItem[];
  coverageWarning?: WarningMessage | null;
}

function confidenceTone(
  confidence: TestSuggestionItem["confidence"],
): "success" | "warning" | "danger" {
  if (confidence === "high") {
    return "success";
  }
  if (confidence === "medium") {
    return "warning";
  }
  return "danger";
}

export function TestRecommendationsTable({
  recommendations,
  coverageWarning,
}: TestRecommendationsTableProps) {
  return (
    <section className="surface-block" aria-labelledby="test-recommendations-title">
      <div className="section-copy">
        <p className="section-kicker">Tests</p>
        <h2 id="test-recommendations-title">Recommended test reruns</h2>
        <p>
          This panel reflects persisted P6 recommendation results from the backend,
          including confidence, merged relation evidence, and optional coverage-backed
          promotion.
        </p>
      </div>

      {coverageWarning ? (
        <div className="info-banner info-banner-warning" role="note">
          <strong>Baseline recommendation only.</strong>
          <span>{coverageWarning.message}</span>
        </div>
      ) : null}

      {recommendations.length ? (
        <div className="table-scroll">
          <table className="impact-table">
            <thead>
              <tr>
                <th>Test</th>
                <th>File</th>
                <th>Score</th>
                <th>Confidence</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {recommendations.map((recommendation) => (
                <tr key={recommendation.test_symbol_id}>
                  <td>
                    <strong>{recommendation.test_name}</strong>
                    <div className="muted-code">{recommendation.reason}</div>
                  </td>
                  <td>
                    <span className="muted-code">{recommendation.file_path}</span>
                  </td>
                  <td>{recommendation.score.toFixed(4)}</td>
                  <td>
                    <StatusBadge
                      label={recommendation.confidence}
                      tone={confidenceTone(recommendation.confidence)}
                    />
                  </td>
                  <td>
                    <div className="impact-detail-list">
                      <span>
                        Relation: {recommendation.reasons_json.relation_type}
                      </span>
                      <span>
                        Matched impact: {recommendation.reasons_json.matched_impacted_symbol}
                      </span>
                      <span>Hops: {recommendation.reasons_json.hop_count}</span>
                      <span>
                        Paths merged: {recommendation.reasons_json.merged_paths_count}
                      </span>
                      <span>
                        Direct test hit:{" "}
                        {recommendation.reasons_json.is_direct_test_hit ? "yes" : "no"}
                      </span>
                      <span>
                        Coverage used:{" "}
                        {recommendation.reasons_json.whether_coverage_used ? "yes" : "no"}
                      </span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="message message-muted">
          No test recommendations are available for this analysis yet.
        </p>
      )}
    </section>
  );
}
