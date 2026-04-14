import { useEffect, useState } from "react";

type HealthState = "checking" | "ok" | "unavailable";

export default function App() {
  const [health, setHealth] = useState<HealthState>("checking");

  useEffect(() => {
    const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";

    fetch(`${apiBase}/api/v1/health`)
      .then((response) => {
        if (!response.ok) {
          throw new Error("Health check failed");
        }
        return response.json() as Promise<{ status: string }>;
      })
      .then((data) => {
        setHealth(data.status === "ok" ? "ok" : "unavailable");
      })
      .catch(() => setHealth("unavailable"));
  }, []);

  return (
    <main className="app-shell">
      <section className="intro-band">
        <p className="eyebrow">B-Impact P0</p>
        <h1>Python change-impact workspace</h1>
        <p className="intro-copy">
          Register a Python repository, start an analysis task, and review the placeholder result
          contract before the analysis engine is implemented.
        </p>
      </section>

      <section className="status-band" aria-labelledby="status-title">
        <div>
          <p className="eyebrow">API status</p>
          <h2 id="status-title">{health === "ok" ? "Backend is reachable" : "Backend pending"}</h2>
        </div>
        <span className={`status-pill status-${health}`}>{health}</span>
      </section>

      <section className="endpoint-band" aria-labelledby="endpoint-title">
        <h2 id="endpoint-title">Available API surface</h2>
        <ul>
          <li>
            <code>GET /api/v1/health</code>
          </li>
          <li>
            <code>POST /api/v1/repositories</code>
          </li>
          <li>
            <code>POST /api/v1/analyses</code>
          </li>
          <li>
            <code>GET /api/v1/analyses/{"{analysis_id}"}</code>
          </li>
          <li>
            <code>GET /api/v1/analyses/{"{analysis_id}"}/report</code>
          </li>
        </ul>
      </section>
    </main>
  );
}

