/**
 * MetricCard — reusable metric display card with confidence label.
 * Acceptance criterion §4.3: MetricCard component for reuse across pages.
 */

import type { ReactNode } from "react";
import ConfidenceBadge from "./ConfidenceBadge";

export interface MetricCardProps {
  label: string;
  value: ReactNode;
  unit?: string;
  conclusionStatus?: string;
  hint?: string;
}

export default function MetricCard({
  label,
  value,
  unit,
  conclusionStatus,
  hint,
}: MetricCardProps) {
  return (
    <div className="metric-card">
      <span className="metric-card-label">{label}</span>
      <div className="metric-card-value">
        {value}
        {unit && <span style={{ marginLeft: 4, fontSize: 13, color: "var(--color-text-secondary)" }}>{unit}</span>}
      </div>
      {conclusionStatus && <ConfidenceBadge status={conclusionStatus} />}
      {hint && <small style={{ color: "var(--color-text-secondary)", fontSize: 11 }}>{hint}</small>}
    </div>
  );
}
