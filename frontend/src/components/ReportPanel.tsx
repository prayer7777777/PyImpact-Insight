interface ReportPanelProps {
  report: string;
}

export function ReportPanel({ report }: ReportPanelProps) {
  return (
    <section className="surface-block" aria-labelledby="report-title">
      <div className="section-copy">
        <p className="section-kicker">Report</p>
        <h2 id="report-title">Markdown report</h2>
        <p>The backend generates this report from the same persisted analysis result returned by the API.</p>
      </div>

      {report ? (
        <pre className="report-viewer">{report}</pre>
      ) : (
        <p className="message message-muted">No report has been loaded yet.</p>
      )}
    </section>
  );
}
