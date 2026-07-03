interface PeriodSelectorProps {
  value?: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  label?: string;
}

export default function PeriodSelector({
  value,
  options,
  onChange,
  label = "报告期",
}: PeriodSelectorProps) {
  return (
    <div className="period-selector">
      {label && <span className="quality-title">{label}</span>}
      <div className="period-buttons">
        {options.map((opt) => (
          <button
            key={opt.value}
            className={`period-btn ${value === opt.value ? "active" : ""}`}
            onClick={() => onChange(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}
