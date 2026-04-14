import type { RecentAnalysisItem, RepositoryRead } from "../api/types";

interface RecentAnalysisListProps {
  analyses: RecentAnalysisItem[];
  repositories: RepositoryRead[];
  selectedAnalysisId: string;
  loading: boolean;
  onSelect: (analysisId: string) => void;
}

export function RecentAnalysisList({
  analyses,
  repositories,
  selectedAnalysisId,
  loading,
  onSelect,
}: RecentAnalysisListProps) {
  const repoNameById = new Map(repositories.map((repository) => [repository.repository_id, repository.name]));

  return (
    <section className="surface-block" aria-labelledby="recent-analyses-title">
      <div className="section-copy">
        <p className="section-kicker">Recent analyses</p>
        <h2 id="recent-analyses-title">Browser-local history</h2>
        <p>These entries are kept in local browser storage because the current backend exposes create and fetch flows, not list endpoints.</p>
      </div>

      {analyses.length ? (
        <div className="recent-list">
          {analyses.map((item) => (
            <button
              key={item.analysis_id}
              className={`recent-item ${item.analysis_id === selectedAnalysisId ? "recent-item-active" : ""}`}
              type="button"
              onClick={() => onSelect(item.analysis_id)}
              disabled={loading}
            >
              <strong>{repoNameById.get(item.repository_id) ?? item.repository_id}</strong>
              <span>{item.analysis_id}</span>
              <span>{new Date(item.created_at).toLocaleString()}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="message message-muted">No local analysis history yet. Create an analysis to populate this panel.</p>
      )}
    </section>
  );
}
