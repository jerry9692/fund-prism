import { useState } from "react";

interface DateRangePickerProps {
  startDate?: string;
  endDate?: string;
  onChange: (range: { startDate: string; endDate: string }) => void;
  label?: string;
  presets?: { label: string; days: number }[];
}

const DEFAULT_PRESETS = [
  { label: "近3月", days: 90 },
  { label: "近6月", days: 180 },
  { label: "近1年", days: 365 },
  { label: "近3年", days: 1095 },
];

export default function DateRangePicker({
  startDate,
  endDate,
  onChange,
  label = "日期范围",
  presets = DEFAULT_PRESETS,
}: DateRangePickerProps) {
  const [localStart, setLocalStart] = useState(startDate || "");
  const [localEnd, setLocalEnd] = useState(endDate || "");

  const handleApply = () => {
    if (localStart && localEnd) {
      onChange({ startDate: localStart, endDate: localEnd });
    }
  };

  const handlePreset = (days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - days);
    const s = start.toISOString().split("T")[0];
    const e = end.toISOString().split("T")[0];
    setLocalStart(s);
    setLocalEnd(e);
    onChange({ startDate: s, endDate: e });
  };

  return (
    <div className="date-range-picker">
      {label && <span className="quality-title">{label}</span>}
      <div className="date-range-inputs">
        <input
          type="date"
          value={localStart}
          onChange={(e) => setLocalStart(e.target.value)}
          className="date-input"
        />
        <span className="date-separator">—</span>
        <input
          type="date"
          value={localEnd}
          onChange={(e) => setLocalEnd(e.target.value)}
          className="date-input"
        />
        <button className="btn btn-sm btn-ghost" onClick={handleApply}>
          应用
        </button>
      </div>
      {presets.length > 0 && (
        <div className="date-presets">
          {presets.map((p) => (
            <button
              key={p.label}
              className="btn btn-sm btn-ghost preset-btn"
              onClick={() => handlePreset(p.days)}
            >
              {p.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
