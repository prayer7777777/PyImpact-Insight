import { useState } from "react";
import type { FormEvent } from "react";

import type { RepositoryCreateInput } from "../api/types";

interface RepositoryFormProps {
  loading: boolean;
  error: string | null;
  onSubmit: (input: RepositoryCreateInput) => Promise<void>;
}

export function RepositoryForm({ loading, error, onSubmit }: RepositoryFormProps) {
  const [form, setForm] = useState<RepositoryCreateInput>({
    name: "sample-service",
    repo_path: "",
    main_branch: "main",
  });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSubmit({
      name: form.name.trim(),
      repo_path: form.repo_path.trim(),
      main_branch: form.main_branch?.trim() || undefined,
    });
  }

  function updateField<K extends keyof RepositoryCreateInput>(key: K, value: RepositoryCreateInput[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  return (
    <form className="workbench-form" onSubmit={handleSubmit}>
      <div className="section-copy">
        <p className="section-kicker">Repository</p>
        <h2>Register a Python Git repository</h2>
        <p>Use a local repository path. The backend validates existence, readability, and `.git` presence.</p>
      </div>

      <label className="field">
        <span>Name</span>
        <input
          required
          value={form.name}
          onChange={(event) => updateField("name", event.target.value)}
          placeholder="sample-service"
        />
      </label>

      <label className="field">
        <span>Repository path</span>
        <input
          required
          value={form.repo_path}
          onChange={(event) => updateField("repo_path", event.target.value)}
          placeholder="/absolute/path/to/repo"
        />
      </label>

      <label className="field">
        <span>Main branch</span>
        <input
          value={form.main_branch ?? ""}
          onChange={(event) => updateField("main_branch", event.target.value)}
          placeholder="main"
        />
      </label>

      {error ? <p className="message message-error">{error}</p> : null}

      <button className="primary-button" type="submit" disabled={loading}>
        {loading ? "Creating repository..." : "Create repository"}
      </button>
    </form>
  );
}
