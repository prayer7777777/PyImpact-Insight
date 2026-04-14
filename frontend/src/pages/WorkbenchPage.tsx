import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import {
  createAnalysis,
  createRepository,
  getAnalysis,
  getAnalysisReport,
  getErrorMessage,
  getHealth,
} from "../api/client";
import type {
  AnalysisCreateInput,
  AnalysisResult,
  RecentAnalysisItem,
  RepositoryCreateInput,
  RepositoryRead,
} from "../api/types";
import { AnalysisForm } from "../components/AnalysisForm";
import { ImpactsTable } from "../components/ImpactsTable";
import { RecentAnalysisList } from "../components/RecentAnalysisList";
import { ReportPanel } from "../components/ReportPanel";
import { RepositoryForm } from "../components/RepositoryForm";
import { StatusBadge } from "../components/StatusBadge";
import { SummaryPanel } from "../components/SummaryPanel";

type HealthState = "checking" | "ok" | "unavailable";

const STORAGE_KEYS = {
  repositories: "b-impact.repositories",
  analyses: "b-impact.analyses",
};

function readStorage<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) {
      return fallback;
    }
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function writeStorage<T>(key: string, value: T) {
  window.localStorage.setItem(key, JSON.stringify(value));
}

function upsertRepository(
  repositories: RepositoryRead[],
  nextRepository: RepositoryRead,
): RepositoryRead[] {
  const filtered = repositories.filter(
    (repository) => repository.repository_id !== nextRepository.repository_id,
  );
  return [nextRepository, ...filtered];
}

function upsertAnalysis(
  analyses: RecentAnalysisItem[],
  nextAnalysis: RecentAnalysisItem,
): RecentAnalysisItem[] {
  const filtered = analyses.filter((analysis) => analysis.analysis_id !== nextAnalysis.analysis_id);
  return [nextAnalysis, ...filtered].slice(0, 12);
}

function apiBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL ?? "";
}

export default function WorkbenchPage() {
  const [health, setHealth] = useState<HealthState>("checking");
  const [repositories, setRepositories] = useState<RepositoryRead[]>(() =>
    typeof window === "undefined" ? [] : readStorage<RepositoryRead[]>(STORAGE_KEYS.repositories, []),
  );
  const [recentAnalyses, setRecentAnalyses] = useState<RecentAnalysisItem[]>(() =>
    typeof window === "undefined"
      ? []
      : readStorage<RecentAnalysisItem[]>(STORAGE_KEYS.analyses, []),
  );
  const [selectedRepositoryId, setSelectedRepositoryId] = useState("");
  const [selectedAnalysisId, setSelectedAnalysisId] = useState("");
  const [analysisLookupId, setAnalysisLookupId] = useState("");
  const [repositoryLoading, setRepositoryLoading] = useState(false);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [resultLoading, setResultLoading] = useState(false);
  const [repositoryError, setRepositoryError] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [resultError, setResultError] = useState<string | null>(null);
  const [currentAnalysis, setCurrentAnalysis] = useState<AnalysisResult | null>(null);
  const [reportContent, setReportContent] = useState("");

  useEffect(() => {
    writeStorage(STORAGE_KEYS.repositories, repositories);
  }, [repositories]);

  useEffect(() => {
    writeStorage(STORAGE_KEYS.analyses, recentAnalyses);
  }, [recentAnalyses]);

  useEffect(() => {
    if (!selectedRepositoryId && repositories.length > 0) {
      setSelectedRepositoryId(repositories[0].repository_id);
    }
  }, [repositories, selectedRepositoryId]);

  useEffect(() => {
    let cancelled = false;

    getHealth()
      .then((payload) => {
        if (!cancelled) {
          setHealth(payload.status === "ok" ? "ok" : "unavailable");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setHealth("unavailable");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const selectedRepository = useMemo(
    () => repositories.find((repository) => repository.repository_id === selectedRepositoryId) ?? null,
    [repositories, selectedRepositoryId],
  );

  async function loadAnalysisBundle(
    analysisId: string,
    fallbackMeta?: Pick<RecentAnalysisItem, "repository_id" | "created_at">,
  ) {
    setResultLoading(true);
    setResultError(null);
    setSelectedAnalysisId(analysisId);

    try {
      const [analysis, report] = await Promise.all([
        getAnalysis(analysisId),
        getAnalysisReport(analysisId),
      ]);
      setCurrentAnalysis(analysis);
      setReportContent(report);
      setSelectedRepositoryId(analysis.repository_id);
      setRecentAnalyses((current) =>
        upsertAnalysis(current, {
          analysis_id: analysis.analysis_id,
          repository_id: analysis.repository_id,
          created_at: fallbackMeta?.created_at ?? new Date().toISOString(),
        }),
      );
      setAnalysisLookupId(analysis.analysis_id);
    } catch (error) {
      setCurrentAnalysis(null);
      setReportContent("");
      setResultError(getErrorMessage(error));
    } finally {
      setResultLoading(false);
    }
  }

  async function handleRepositorySubmit(input: RepositoryCreateInput) {
    setRepositoryLoading(true);
    setRepositoryError(null);

    try {
      const repository = await createRepository(input);
      setRepositories((current) => upsertRepository(current, repository));
      setSelectedRepositoryId(repository.repository_id);
    } catch (error) {
      setRepositoryError(getErrorMessage(error));
    } finally {
      setRepositoryLoading(false);
    }
  }

  async function handleAnalysisSubmit(input: AnalysisCreateInput) {
    setAnalysisLoading(true);
    setAnalysisError(null);

    try {
      const accepted = await createAnalysis(input);
      await loadAnalysisBundle(accepted.analysis_id, {
        repository_id: accepted.repository_id,
        created_at: accepted.created_at,
      });
      setRecentAnalyses((current) =>
        upsertAnalysis(current, {
          analysis_id: accepted.analysis_id,
          repository_id: accepted.repository_id,
          created_at: accepted.created_at,
        }),
      );
    } catch (error) {
      setAnalysisError(getErrorMessage(error));
    } finally {
      setAnalysisLoading(false);
    }
  }

  async function handleLookupSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!analysisLookupId.trim()) {
      return;
    }
    await loadAnalysisBundle(analysisLookupId.trim());
  }

  return (
    <main className="workbench-shell">
      <section className="headline-band">
        <div className="headline-copy">
          <p className="section-kicker">B-Impact P5.5</p>
          <h1>Python change-impact workbench</h1>
          <p>
            Register a repository, run a real analysis, inspect summary metrics, and review scored impacts from the current P5 backend.
          </p>
        </div>
        <div className="headline-status">
          <div>
            <span className="meta-label">API health</span>
            <strong>{health === "ok" ? "Backend reachable" : health === "checking" ? "Checking backend" : "Backend unavailable"}</strong>
          </div>
          <StatusBadge
            label={health}
            tone={health === "ok" ? "success" : health === "checking" ? "neutral" : "danger"}
          />
        </div>
      </section>

      <section className="workspace-grid">
        <aside className="control-rail">
          <RepositoryForm
            loading={repositoryLoading}
            error={repositoryError}
            onSubmit={handleRepositorySubmit}
          />

          <section className="surface-block" aria-labelledby="repo-list-title">
            <div className="section-copy">
              <p className="section-kicker">Repositories</p>
              <h2 id="repo-list-title">Available in this browser</h2>
            </div>

            {repositories.length ? (
              <div className="recent-list">
                {repositories.map((repository) => (
                  <button
                    key={repository.repository_id}
                    className={`recent-item ${repository.repository_id === selectedRepositoryId ? "recent-item-active" : ""}`}
                    type="button"
                    onClick={() => setSelectedRepositoryId(repository.repository_id)}
                  >
                    <strong>{repository.name}</strong>
                    <span>{repository.repo_path}</span>
                    <span>{repository.repository_id}</span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="message message-muted">No repository has been created from this browser yet.</p>
            )}
          </section>

          <AnalysisForm
            loading={analysisLoading}
            error={analysisError}
            repositories={repositories}
            selectedRepositoryId={selectedRepositoryId}
            onRepositoryChange={setSelectedRepositoryId}
            onSubmit={handleAnalysisSubmit}
          />

          <RecentAnalysisList
            analyses={recentAnalyses}
            repositories={repositories}
            selectedAnalysisId={selectedAnalysisId}
            loading={resultLoading}
            onSelect={(analysisId) => void loadAnalysisBundle(analysisId)}
          />

          <section className="surface-block" aria-labelledby="lookup-title">
            <div className="section-copy">
              <p className="section-kicker">Lookup</p>
              <h2 id="lookup-title">Load an analysis by ID</h2>
              <p>Use this when you already have an analysis ID and want to pull the latest persisted result and report.</p>
            </div>

            <form className="workbench-form compact-form" onSubmit={handleLookupSubmit}>
              <label className="field">
                <span>Analysis ID</span>
                <input
                  value={analysisLookupId}
                  onChange={(event) => setAnalysisLookupId(event.target.value)}
                  placeholder="analysis UUID"
                />
              </label>
              <button className="secondary-button" type="submit" disabled={resultLoading}>
                {resultLoading ? "Loading..." : "Load analysis"}
              </button>
            </form>
          </section>
        </aside>

        <section className="results-pane">
          {selectedRepository ? (
            <section className="surface-block" aria-labelledby="selection-title">
              <div className="section-copy">
                <p className="section-kicker">Selection</p>
                <h2 id="selection-title">Current repository context</h2>
              </div>

              <div className="selection-grid">
                <div>
                  <span className="meta-label">Name</span>
                  <strong>{selectedRepository.name}</strong>
                </div>
                <div>
                  <span className="meta-label">Main branch</span>
                  <strong>{selectedRepository.main_branch}</strong>
                </div>
                <div>
                  <span className="meta-label">Repository ID</span>
                  <strong className="muted-code">{selectedRepository.repository_id}</strong>
                </div>
                <div>
                  <span className="meta-label">Path</span>
                  <strong className="muted-code">{selectedRepository.repo_path}</strong>
                </div>
              </div>
            </section>
          ) : (
            <section className="surface-block">
              <p className="message message-muted">Create a repository to unlock analysis controls and recent results.</p>
            </section>
          )}

          {resultLoading ? (
            <section className="surface-block">
              <p className="message">Loading analysis result and report...</p>
            </section>
          ) : null}

          {resultError ? (
            <section className="surface-block">
              <p className="message message-error">{resultError}</p>
            </section>
          ) : null}

          {currentAnalysis ? (
            <>
              <section className="surface-block" aria-labelledby="analysis-status-title">
                <div className="analysis-header">
                  <div className="section-copy">
                    <p className="section-kicker">Analysis</p>
                    <h2 id="analysis-status-title">Latest loaded result</h2>
                    <p>Direct link: <a href={`${apiBaseUrl()}/api/v1/analyses/${currentAnalysis.analysis_id}/report`} target="_blank" rel="noreferrer">Markdown report</a></p>
                  </div>
                  <div className="analysis-meta">
                    <StatusBadge
                      label={currentAnalysis.status}
                      tone={currentAnalysis.status === "COMPLETED" ? "success" : currentAnalysis.status === "FAILED" ? "danger" : "warning"}
                    />
                    <div className="meta-stack">
                      <span className="meta-label">Analysis ID</span>
                      <strong className="muted-code">{currentAnalysis.analysis_id}</strong>
                    </div>
                  </div>
                </div>

                {currentAnalysis.warnings.length ? (
                  <div className="warning-list">
                    {currentAnalysis.warnings.map((warning) => (
                      <p key={warning.code} className="message message-warning">
                        <strong>{warning.code}</strong>: {warning.message}
                      </p>
                    ))}
                  </div>
                ) : null}
              </section>

              <SummaryPanel summary={currentAnalysis.summary} />
              <ImpactsTable impacts={currentAnalysis.impacts} />
              <ReportPanel report={reportContent} />
            </>
          ) : !resultLoading && !resultError ? (
            <section className="surface-block">
              <div className="section-copy">
                <p className="section-kicker">Results</p>
                <h2>No analysis loaded yet</h2>
                <p>Run an analysis or load one by ID to inspect real P5 summary metrics, scored impacts, and the generated report.</p>
              </div>
            </section>
          ) : null}
        </section>
      </section>
    </main>
  );
}
