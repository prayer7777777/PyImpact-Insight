import { useMemo, useState } from "react";
import type { FormEvent } from "react";

import type { AnalysisCreateInput, DiffMode, RepositoryRead } from "../api/types";

interface AnalysisFormProps {
  loading: boolean;
  error: string | null;
  repositories: RepositoryRead[];
  selectedRepositoryId: string;
  onRepositoryChange: (repositoryId: string) => void;
  onSubmit: (input: AnalysisCreateInput) => Promise<void>;
}

interface AnalysisFormState {
  repository_id: string;
  diff_mode: DiffMode;
  commit_from: string;
  commit_to: string;
  base_ref: string;
  head_ref: string;
  include_untracked: boolean;
  use_coverage: boolean;
  max_depth: number;
}

export function AnalysisForm({
  loading,
  error,
  repositories,
  selectedRepositoryId,
  onRepositoryChange,
  onSubmit,
}: AnalysisFormProps) {
  const [form, setForm] = useState<AnalysisFormState>({
    repository_id: selectedRepositoryId,
    diff_mode: "working_tree",
    commit_from: "",
    commit_to: "",
    base_ref: "",
    head_ref: "",
    include_untracked: false,
    use_coverage: false,
    max_depth: 4,
  });

  const repositoryOptions = useMemo(
    () =>
      repositories.map((repository) => ({
        value: repository.repository_id,
        label: `${repository.name} · ${repository.main_branch}`,
      })),
    [repositories],
  );

  const effectiveRepositoryId = form.repository_id || selectedRepositoryId;

  function updateField<K extends keyof AnalysisFormState>(key: K, value: AnalysisFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    if (key === "repository_id") {
      onRepositoryChange(String(value));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const payload: AnalysisCreateInput = {
      repository_id: effectiveRepositoryId,
      diff_mode: form.diff_mode,
      include_untracked: form.include_untracked,
      options: {
        max_depth: Number(form.max_depth),
        include_tests: true,
        use_coverage: form.use_coverage,
      },
    };

    if (form.diff_mode === "commit_range") {
      payload.commit_from = form.commit_from.trim();
      payload.commit_to = form.commit_to.trim();
    }

    if (form.diff_mode === "refs_compare") {
      payload.base_ref = form.base_ref.trim();
      payload.head_ref = form.head_ref.trim();
    }

    await onSubmit(payload);
  }

  const needsCommitRange = form.diff_mode === "commit_range";
  const needsRefsCompare = form.diff_mode === "refs_compare";

  return (
    <form className="workbench-form" onSubmit={handleSubmit}>
      <div className="section-copy">
        <p className="section-kicker">Analysis</p>
        <h2>Run a real P6 analysis</h2>
        <p>
          The current backend supports diff mapping, structural propagation, final
          impact scoring, and explainable test recommendations.
        </p>
      </div>

      <label className="field">
        <span>Repository</span>
        <select
          required
          value={effectiveRepositoryId}
          onChange={(event) => updateField("repository_id", event.target.value)}
        >
          <option value="" disabled>
            Select a repository
          </option>
          {repositoryOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <div className="inline-fields">
        <label className="field">
          <span>Diff mode</span>
          <select
            value={form.diff_mode}
            onChange={(event) => updateField("diff_mode", event.target.value as DiffMode)}
          >
            <option value="working_tree">working_tree</option>
            <option value="commit_range">commit_range</option>
            <option value="refs_compare">refs_compare</option>
          </select>
        </label>

        <label className="field">
          <span>Max depth</span>
          <input
            min={1}
            max={20}
            type="number"
            value={form.max_depth}
            onChange={(event) => updateField("max_depth", Number(event.target.value))}
          />
        </label>
      </div>

      {needsCommitRange ? (
        <div className="inline-fields">
          <label className="field">
            <span>Commit from</span>
            <input
              required={needsCommitRange}
              value={form.commit_from}
              onChange={(event) => updateField("commit_from", event.target.value)}
              placeholder="base commit SHA"
            />
          </label>
          <label className="field">
            <span>Commit to</span>
            <input
              required={needsCommitRange}
              value={form.commit_to}
              onChange={(event) => updateField("commit_to", event.target.value)}
              placeholder="target commit SHA"
            />
          </label>
        </div>
      ) : null}

      {needsRefsCompare ? (
        <div className="inline-fields">
          <label className="field">
            <span>Base ref</span>
            <input
              required={needsRefsCompare}
              value={form.base_ref}
              onChange={(event) => updateField("base_ref", event.target.value)}
              placeholder="main"
            />
          </label>
          <label className="field">
            <span>Head ref</span>
            <input
              required={needsRefsCompare}
              value={form.head_ref}
              onChange={(event) => updateField("head_ref", event.target.value)}
              placeholder="feature-branch"
            />
          </label>
        </div>
      ) : null}

      <label className="checkbox-field">
        <input
          type="checkbox"
          checked={form.include_untracked}
          onChange={(event) => updateField("include_untracked", event.target.checked)}
        />
        <span>Include untracked files for working_tree</span>
      </label>

      <label className="checkbox-field">
        <input
          type="checkbox"
          checked={form.use_coverage}
          onChange={(event) => updateField("use_coverage", event.target.checked)}
        />
        <span>Use coverage contexts when a supported coverage.json artifact exists</span>
      </label>

      {error ? <p className="message message-error">{error}</p> : null}

      <button
        className="primary-button"
        type="submit"
        disabled={loading || !effectiveRepositoryId}
      >
        {loading ? "Running analysis..." : "Create analysis"}
      </button>
    </form>
  );
}
