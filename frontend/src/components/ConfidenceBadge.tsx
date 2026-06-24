/**
 * ConfidenceBadge — conclusion status badge.
 * Acceptance criterion §4.3: ConfidenceBadge for fact/computed/estimated/
 * observation/needs_review statuses.
 */

const STATUS_LABELS: Record<string, string> = {
  fact: "事实",
  computed: "计算",
  estimated: "估计",
  observation: "观察",
  needs_review: "待审",
};

const STATUS_LABELS_EN: Record<string, string> = {
  fact: "Fact",
  computed: "Computed",
  estimated: "Estimated",
  observation: "Observation",
  needs_review: "Needs Review",
};

export interface ConfidenceBadgeProps {
  status: string;
  showEnglish?: boolean;
}

export default function ConfidenceBadge({ status, showEnglish = false }: ConfidenceBadgeProps) {
  const label = showEnglish
    ? STATUS_LABELS_EN[status] ?? status
    : STATUS_LABELS[status] ?? status;
  return (
    <span className={`badge badge-${status}`}>
      {label}
    </span>
  );
}
