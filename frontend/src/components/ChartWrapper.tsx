/**
 * ChartWrapper — pluggable chart component.
 *
 * Provides a unified interface for bar and line charts. The current
 * implementation uses pure SVG so no external dependency is required.
 * To switch to Recharts/ECharts, replace the render functions below
 * while keeping the same props interface — pages do not need to change.
 *
 * Acceptance criterion §4.3 / §10.7: chart components must be
 * switchable via ChartWrapper.
 */

export interface BarSeries {
  label: string;
  values: number[];
}

export interface LinePoint {
  x: string;
  y: number;
}

export interface ChartWrapperProps {
  type: "bar" | "line";
  title?: string;
  /** Bar chart: labels for X axis. */
  labels?: string[];
  /** Bar chart: one or more series. */
  series?: BarSeries[];
  /** Line chart: data points. */
  data?: LinePoint[];
  /** Y-axis label. */
  yLabel?: string;
  height?: number;
  /** Optional formatter for Y-axis values (e.g. percent). */
  formatY?: (v: number) => string;
}

const COLORS = [
  "var(--color-primary)",
  "var(--color-success)",
  "var(--color-warning)",
  "var(--color-danger)",
];

export default function ChartWrapper({
  type,
  title,
  labels = [],
  series = [],
  data = [],
  yLabel,
  height = 240,
  formatY = (v) => v.toFixed(2),
}: ChartWrapperProps) {
  const width = 600;
  const padding = { top: 20, right: 20, bottom: 40, left: 60 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;

  // Compute Y domain
  let yMin = 0;
  let yMax = 0;
  if (type === "bar") {
    for (const s of series) {
      for (const v of s.values) {
        yMin = Math.min(yMin, v);
        yMax = Math.max(yMax, v);
      }
    }
  } else {
    for (const p of data) {
      yMin = Math.min(yMin, p.y);
      yMax = Math.max(yMax, p.y);
    }
  }
  // Add 10% padding
  const range = yMax - yMin || 1;
  yMax += range * 0.1;
  yMin -= range * 0.1;
  if (yMin > 0) yMin = 0;

  const yScale = (v: number) =>
    padding.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

  // Y-axis ticks
  const tickCount = 5;
  const ticks = Array.from({ length: tickCount + 1 }, (_, i) => {
    return yMin + (i / tickCount) * (yMax - yMin);
  });

  // Zero line position
  const zeroY = yScale(0);

  return (
    <div className="card" style={{ padding: 16 }}>
      {title && <h4 style={{ marginBottom: 12 }}>{title}</h4>}
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: "100%", height: "auto", maxWidth: "100%" }}
      >
        {/* Y-axis grid lines and labels */}
        {ticks.map((t, i) => {
          const y = yScale(t);
          return (
            <g key={i}>
              <line
                x1={padding.left}
                y1={y}
                x2={width - padding.right}
                y2={y}
                stroke="var(--color-border)"
                strokeWidth={1}
                strokeDasharray={i === 0 ? "0" : "2 4"}
              />
              <text
                x={padding.left - 8}
                y={y + 4}
                textAnchor="end"
                fontSize={10}
                fill="var(--color-text-secondary)"
              >
                {formatY(t)}
              </text>
            </g>
          );
        })}

        {/* Zero line emphasis */}
        {yMin < 0 && yMax > 0 && (
          <line
            x1={padding.left}
            y1={zeroY}
            x2={width - padding.right}
            y2={zeroY}
            stroke="var(--color-text-secondary)"
            strokeWidth={1.5}
          />
        )}

        {/* Y-axis label */}
        {yLabel && (
          <text
            x={12}
            y={height / 2}
            textAnchor="middle"
            fontSize={11}
            fill="var(--color-text-secondary)"
            transform={`rotate(-90 12 ${height / 2})`}
          >
            {yLabel}
          </text>
        )}

        {type === "bar" && renderBar(labels, series, padding, plotW, plotH, yScale, zeroY)}
        {type === "line" && renderLine(data, padding, plotW, plotH, yScale)}
      </svg>
    </div>
  );
}

function renderBar(
  labels: string[],
  series: BarSeries[],
  padding: { top: number; right: number; bottom: number; left: number },
  plotW: number,
  _plotH: number,
  yScale: (v: number) => number,
  zeroY: number,
) {
  if (labels.length === 0 || series.length === 0) return null;

  const groupW = plotW / labels.length;
  const barW = (groupW * 0.7) / series.length;
  const groupPadding = groupW * 0.15;

  return (
    <>
      {labels.map((label, gi) => {
        const groupX = padding.left + gi * groupW + groupPadding;
        return (
          <g key={gi}>
            {series.map((s, si) => {
              const v = s.values[gi] ?? 0;
              const y = yScale(v);
              const h = Math.abs(zeroY - y);
              const x = groupX + si * barW;
              return (
                <rect
                  key={si}
                  x={x}
                  y={Math.min(y, zeroY)}
                  width={barW - 2}
                  height={h}
                  fill={COLORS[si % COLORS.length]}
                  rx={2}
                >
                  <title>{`${s.label}: ${v.toFixed(4)}`}</title>
                </rect>
              );
            })}
            <text
              x={groupX + (groupW - groupPadding * 2) / 2}
              y={padding.top + _plotH + 18}
              textAnchor="middle"
              fontSize={10}
              fill="var(--color-text-secondary)"
            >
              {label}
            </text>
          </g>
        );
      })}
      {/* Legend */}
      {series.length > 1 && (
        <g transform={`translate(${padding.left}, ${padding.top - 4})`}>
          {series.map((s, si) => (
            <g key={si} transform={`translate(${si * 100}, 0)`}>
              <rect width={12} height={12} fill={COLORS[si % COLORS.length]} rx={2} />
              <text x={16} y={10} fontSize={10} fill="var(--color-text-secondary)">
                {s.label}
              </text>
            </g>
          ))}
        </g>
      )}
    </>
  );
}

function renderLine(
  data: LinePoint[],
  padding: { top: number; right: number; bottom: number; left: number },
  plotW: number,
  plotH: number,
  yScale: (v: number) => number,
) {
  if (data.length === 0) return null;

  const stepX = plotW / Math.max(data.length - 1, 1);
  const points = data.map((p, i) => ({
    x: padding.left + i * stepX,
    y: yScale(p.y),
    label: p.x,
    value: p.y,
  }));

  const pathD = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`)
    .join(" ");

  return (
    <>
      <path
        d={pathD}
        fill="none"
        stroke="var(--color-primary)"
        strokeWidth={2}
      />
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r={3} fill="var(--color-primary)">
            <title>{`${p.label}: ${p.value.toFixed(4)}`}</title>
          </circle>
          {i % Math.ceil(data.length / 8) === 0 && (
            <text
              x={p.x}
              y={padding.top + plotH + 18}
              textAnchor="middle"
              fontSize={9}
              fill="var(--color-text-secondary)"
              transform={`rotate(-30 ${p.x} ${padding.top + plotH + 18})`}
            >
              {p.label}
            </text>
          )}
        </g>
      ))}
    </>
  );
}
