import type { AnalysisSummary } from "../api/types";

interface SummaryPanelProps {
  summary: AnalysisSummary;
}

const SUMMARY_ITEMS: Array<{ key: keyof AnalysisSummary; label: string }> = [
  { key: "changed_files", label: "Changed files" },
  { key: "changed_symbols", label: "Changed symbols" },
  { key: "impacted_symbols", label: "Impacted candidates" },
  { key: "impacted_tests", label: "Impacted tests" },
  { key: "high_confidence_impacts", label: "High confidence impacts" },
  { key: "top_impacts", label: "Final impacts" },
];

export function SummaryPanel({ summary }: SummaryPanelProps) {
  return (
    <section className="surface-block" aria-labelledby="summary-title">
      <div className="section-copy">
        <p className="section-kicker">Summary</p>
        <h2 id="summary-title">Analysis overview</h2>
      </div>

      <div className="summary-grid">
        {SUMMARY_ITEMS.map((item) => (
          <div key={item.key} className="metric-tile">
            <span className="metric-label">{item.label}</span>
            <strong className="metric-value">{summary[item.key]}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
