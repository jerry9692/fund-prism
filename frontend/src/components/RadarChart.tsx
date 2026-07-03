/**
 * Radar chart component for scoring dimension visualization.
 * Pure SVG implementation (no external chart library dependency).
 */

export interface RadarAxis {
  key: string;
  label: string;
  value: number; // 0-1 scale
  maxValue?: number;
  color?: string;
}

interface RadarChartProps {
  axes: RadarAxis[];
  size?: number;
  levels?: number;
  fillColor?: string;
  strokeColor?: string;
  showLabels?: boolean;
  showValues?: boolean;
  className?: string;
}

const DEFAULT_SIZE = 280;
const DEFAULT_LEVELS = 4;

export default function RadarChart({
  axes,
  size = DEFAULT_SIZE,
  levels = DEFAULT_LEVELS,
  fillColor = "rgba(212, 165, 116, 0.15)",
  strokeColor = "#d4a574",
  showLabels = true,
  showValues = true,
  className = "",
}: RadarChartProps) {
  if (axes.length < 3) {
    return (
      <div className="empty-state" style={{ padding: "32px" }}>
        至少需要3个维度才能绘制雷达图
      </div>
    );
  }

  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 48; // leave room for labels
  const angleStep = (2 * Math.PI) / axes.length;
  // Start from top (-PI/2)
  const startAngle = -Math.PI / 2;

  // Helper: get point on the radar
  const getPoint = (index: number, value: number) => {
    const angle = startAngle + index * angleStep;
    const r = radius * Math.max(0, Math.min(1, value));
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
    };
  };

  // Helper: get axis endpoint
  const getAxisPoint = (index: number) => getPoint(index, 1);

  // Generate grid polygons
  const gridPolygons = [];
  for (let l = 1; l <= levels; l++) {
    const level = l / levels;
    const points = axes
      .map((_, i) => {
        const p = getPoint(i, level);
        return `${p.x},${p.y}`;
      })
      .join(" ");
    gridPolygons.push(
      <polygon
        key={`grid-${l}`}
        points={points}
        className="radar-grid"
        strokeWidth={l === levels ? 1.5 : 1}
      />
    );
  }

  // Axis lines
  const axisLines = axes.map((_, i) => {
    const p = getAxisPoint(i);
    return (
      <line
        key={`axis-${i}`}
        x1={cx}
        y1={cy}
        x2={p.x}
        y2={p.y}
        className="radar-axis"
      />
    );
  });

  // Data polygon
  const dataPoints = axes.map((a, i) => getPoint(i, a.value));
  const dataPointsStr = dataPoints.map((p) => `${p.x},${p.y}`).join(" ");

  // Data dots
  const dataDots = dataPoints.map((p, i) => (
    <circle
      key={`dot-${i}`}
      cx={p.x}
      cy={p.y}
      r={3.5}
      className="radar-dot"
    />
  ));

  // Labels
  const labels = showLabels
    ? axes.map((a, i) => {
        const angle = startAngle + i * angleStep;
        // Offset labels outward
        const labelR = radius + 28;
        const lx = cx + labelR * Math.cos(angle);
        const ly = cy + labelR * Math.sin(angle);
        // Text anchor
        let anchor: "start" | "middle" | "end" = "middle";
        if (Math.abs(Math.cos(angle)) > 0.3) {
          anchor = Math.cos(angle) > 0 ? "start" : "end";
        }
        return (
          <g key={`label-${i}`}>
            <text
              x={lx}
              y={ly}
              textAnchor={anchor}
              dominantBaseline="middle"
              fill="#a8a29e"
              fontSize={11}
              fontWeight={500}
            >
              {a.label}
            </text>
            {showValues && (
              <text
                x={lx}
                y={ly + 13}
                textAnchor={anchor}
                dominantBaseline="middle"
                fill="#d4a574"
                fontSize={10}
                fontFamily="var(--font-mono)"
              >
                {(a.value * 100).toFixed(0)}分
              </text>
            )}
          </g>
        );
      })
    : null;

  return (
    <div className={`radar-chart-container ${className}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {gridPolygons}
        {axisLines}
        <polygon
          points={dataPointsStr}
          className="radar-area"
          style={{ fill: fillColor, stroke: strokeColor }}
        />
        {dataDots}
        {labels}
      </svg>
    </div>
  );
}
