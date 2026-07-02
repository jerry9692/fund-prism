import type { CSSProperties } from "react";

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
  const style: CSSProperties = disabled
    ? { opacity: 0.5, pointerEvents: "none" }
    : {};

  return (
    <div className="period-tabs" role="tablist" style={style}>
      {options.map((opt) => {
        const isActive = opt === value;
        return (
          <button
            key={opt}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(opt)}
            className={`period-tab${isActive ? " active" : ""}`}
          >
            {PERIOD_LABELS[opt]}
          </button>
        );
      })}
    </div>
  );
}

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
