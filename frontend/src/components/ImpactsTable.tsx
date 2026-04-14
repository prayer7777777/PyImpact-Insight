import type { ImpactItem } from "../api/types";
import { StatusBadge } from "./StatusBadge";

interface ImpactsTableProps {
  impacts: ImpactItem[];
}

function confidenceTone(confidence: ImpactItem["confidence"]): "success" | "warning" | "danger" {
  if (confidence === "high") {
    return "success";
  }
  if (confidence === "medium") {
    return "warning";
  }
  return "danger";
}

export function ImpactsTable({ impacts }: ImpactsTableProps) {
  if (!impacts.length) {
    return (
      <section className="surface-block" aria-labelledby="impacts-title">
        <div className="section-copy">
          <p className="section-kicker">Impacts</p>
          <h2 id="impacts-title">Final ranked impacts</h2>
          <p>No final impacts are available for this analysis.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="surface-block" aria-labelledby="impacts-title">
      <div className="section-copy">
        <p className="section-kicker">Impacts</p>
        <h2 id="impacts-title">Final ranked impacts</h2>
        <p>The table reflects persisted P5 results from the backend. Scores are already ordered descending.</p>
      </div>

      <div className="table-scroll">
        <table className="impact-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Kind</th>
              <th>File</th>
              <th>Score</th>
              <th>Confidence</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {impacts.map((impact) => (
              <tr key={impact.symbol_id}>
                <td>
                  <strong>{impact.symbol_name}</strong>
                  <div className="muted-code">{impact.symbol_key}</div>
                </td>
                <td>{impact.symbol_kind}</td>
                <td>
                  <span className="muted-code">{impact.file_path}</span>
                </td>
                <td>{impact.score.toFixed(4)}</td>
                <td>
                  <StatusBadge label={impact.confidence} tone={confidenceTone(impact.confidence)} />
                </td>
                <td>
                  <div className="impact-detail-list">
                    <span>From: {impact.reasons_json.matched_from_changed_symbol}</span>
                    <span>Edges: {impact.reasons_json.edge_types.join(", ") || "changed_symbol"}</span>
                    <span>Hops: {impact.reasons_json.hop_count}</span>
                    <span>Paths merged: {impact.reasons_json.merged_paths_count}</span>
                    <span>Test symbol: {impact.reasons_json.is_test_symbol ? "yes" : "no"}</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
