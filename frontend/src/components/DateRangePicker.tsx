/**
 * DateRangePicker — start/end date selector.
 * Acceptance criterion §4.3: DateRangePicker for date interval selection.
 */

export interface DateRangePickerProps {
  startDate: string;
  endDate: string;
  onChange: (startDate: string, endDate: string) => void;
  startLabel?: string;
  endLabel?: string;
  minDate?: string;
  maxDate?: string;
  disabled?: boolean;
}

export default function DateRangePicker({
  startDate,
  endDate,
  onChange,
  startLabel = "开始",
  endLabel = "结束",
  minDate,
  maxDate,
  disabled = false,
}: DateRangePickerProps) {
  const inputStyle: React.CSSProperties = {
    padding: "6px 10px",
    fontSize: 14,
    border: "1px solid var(--color-border)",
    borderRadius: 6,
    background: "var(--color-surface)",
    color: "var(--color-text)",
    outline: "none",
    width: 150,
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 12,
    color: "var(--color-text-secondary)",
    marginRight: 4,
  };

  function handleStartChange(value: string) {
    if (endDate && value > endDate) {
      onChange(value, value);
    } else {
      onChange(value, endDate);
    }
  }

  function handleEndChange(value: string) {
    if (startDate && value < startDate) {
      onChange(value, value);
    } else {
      onChange(startDate, value);
    }
  }

  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 12,
        opacity: disabled ? 0.6 : 1,
        pointerEvents: disabled ? "none" : "auto",
      }}
    >
      <div style={{ display: "flex", alignItems: "center" }}>
        <span style={labelStyle}>{startLabel}</span>
        <input
          type="date"
          value={startDate}
          min={minDate}
          max={maxDate}
          onChange={(e) => handleStartChange(e.target.value)}
          style={inputStyle}
        />
      </div>
      <span style={{ color: "var(--color-text-secondary)", fontSize: 13 }}>~</span>
      <div style={{ display: "flex", alignItems: "center" }}>
        <span style={labelStyle}>{endLabel}</span>
        <input
          type="date"
          value={endDate}
          min={minDate}
          max={maxDate}
          onChange={(e) => handleEndChange(e.target.value)}
          style={inputStyle}
        />
      </div>
    </div>
  );
}
