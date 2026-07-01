/**
 * PeriodSelector — multi-period switcher (YTD/1M/3M/6M/1Y/3Y/5Y).
 * Acceptance criterion §4.3: PeriodSelector for quick interval switching.
 */

export type PeriodKey = "YTD" | "1M" | "3M" | "6M" | "1Y" | "3Y" | "5Y";

export interface PeriodSelectorProps {
  value: PeriodKey;
  onChange: (period: PeriodKey) => void;
  options?: PeriodKey[];
  disabled?: boolean;
}

const DEFAULT_OPTIONS: PeriodKey[] = ["YTD", "1M", "3M", "6M", "1Y", "3Y", "5Y"];

const PERIOD_LABELS: Record<PeriodKey, string> = {
  YTD: "今年以来",
  "1M": "近1月",
  "3M": "近3月",
  "6M": "近6月",
  "1Y": "近1年",
  "3Y": "近3年",
  "5Y": "近5年",
};

export default function PeriodSelector({
  value,
  onChange,
  options = DEFAULT_OPTIONS,
  disabled = false,
}: PeriodSelectorProps) {
  return (
    <div
      role="tablist"
      style={{
        display: "inline-flex",
        gap: 2,
        padding: 2,
        background: "var(--color-bg)",
        border: "1px solid var(--color-border)",
        borderRadius: 6,
        opacity: disabled ? 0.6 : 1,
        pointerEvents: disabled ? "none" : "auto",
      }}
    >
      {options.map((opt) => {
        const isActive = opt === value;
        return (
          <button
            key={opt}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(opt)}
            style={{
              padding: "4px 12px",
              fontSize: 13,
              fontWeight: isActive ? 600 : 400,
              border: "none",
              borderRadius: 4,
              cursor: "pointer",
              background: isActive ? "var(--color-surface)" : "transparent",
              color: isActive ? "var(--color-primary)" : "var(--color-text-secondary)",
              boxShadow: isActive ? "0 1px 2px rgba(0,0,0,0.08)" : "none",
              transition: "all 0.15s ease",
            }}
          >
            {PERIOD_LABELS[opt]}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Compute a start date for the given period key, relative to `refDate`.
 * Returns an ISO date string (YYYY-MM-DD). Useful for callers that need
 * to translate a period selection into an explicit date range.
 */
export function periodToStartDate(period: PeriodKey, refDate: Date = new Date()): string {
  const d = new Date(refDate);
  switch (period) {
    case "YTD":
      return `${d.getFullYear()}-01-01`;
    case "1M":
      d.setMonth(d.getMonth() - 1);
      break;
    case "3M":
      d.setMonth(d.getMonth() - 3);
      break;
    case "6M":
      d.setMonth(d.getMonth() - 6);
      break;
    case "1Y":
      d.setFullYear(d.getFullYear() - 1);
      break;
    case "3Y":
      d.setFullYear(d.getFullYear() - 3);
      break;
    case "5Y":
      d.setFullYear(d.getFullYear() - 5);
      break;
  }
  return d.toISOString().slice(0, 10);
}
