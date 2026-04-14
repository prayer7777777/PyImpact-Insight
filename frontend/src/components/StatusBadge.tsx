interface StatusBadgeProps {
  label: string;
  tone: "neutral" | "success" | "warning" | "danger";
}

export function StatusBadge({ label, tone }: StatusBadgeProps) {
  return <span className={`status-badge status-${tone}`}>{label}</span>;
}
