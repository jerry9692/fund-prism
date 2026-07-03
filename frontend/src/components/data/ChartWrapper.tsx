// ChartWrapper — ECharts 统一封装
// 统一主题色板，自动响应式，loading/error 状态

import { useEffect, useRef } from "react";
import * as echarts from "echarts";

const CHART_THEME = {
  color: [
    "#B45309", // accent
    "#3B6EA5", // info
    "#2D7A4F", // positive
    "#6B5B8A", // observation purple
    "#8F8678", // tertiary gray
    "#B23A3A", // negative
  ],
  textStyle: {
    fontFamily: "IBM Plex Sans, Noto Sans SC, sans-serif",
    color: "#5C544A",
  },
  title: {
    textStyle: {
      fontFamily: "Fraunces, Noto Serif SC, serif",
      fontSize: 14,
      fontWeight: 600,
      color: "#1C1814",
    },
  },
  axisLabel: {
    fontFamily: "IBM Plex Mono, monospace",
    color: "#8F8678",
    fontSize: 11,
  },
  axisLine: {
    lineStyle: { color: "#E8E0D4" },
  },
  splitLine: {
    lineStyle: { color: "#E8E0D4", type: "dashed" as const },
  },
  tooltip: {
    backgroundColor: "#FFFCF7",
    borderColor: "#D9CFBE",
    borderWidth: 1,
    textStyle: {
      fontFamily: "IBM Plex Sans, Noto Sans SC, sans-serif",
      color: "#1C1814",
      fontSize: 12,
    },
  },
  legend: {
    textStyle: {
      fontFamily: "IBM Plex Sans, Noto Sans SC, sans-serif",
      color: "#5C544A",
      fontSize: 12,
    },
  },
};

export interface ChartWrapperProps {
  option: echarts.EChartsOption;
  height?: number;
  loading?: boolean;
  error?: string;
}

export function ChartWrapper({
  option,
  height = 280,
  loading = false,
  error,
}: ChartWrapperProps) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current || loading || error) return;

    const chart = echarts.init(ref.current, undefined, {
      renderer: "canvas",
    });
    chartRef.current = chart;

    const merged = {
      ...CHART_THEME,
      ...option,
    };
    chart.setOption(merged);

    const resize = () => chart.resize();
    window.addEventListener("resize", resize);

    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
      chartRef.current = null;
    };
  }, [option, loading, error]);

  // 更新 option 时不重建 chart
  useEffect(() => {
    if (chartRef.current && !loading && !error) {
      chartRef.current.setOption({ ...CHART_THEME, ...option }, { notMerge: true });
    }
  }, [option, loading, error]);

  if (loading) {
    return (
      <div style={{ height }} className="flex items-center justify-center">
        <div className="skeleton skeleton-block" style={{ width: "100%", height: "100%" }} />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ height }} className="flex items-center justify-center">
        <div className="error-state" style={{ width: "100%" }}>
          <div className="error-state-title">图表加载失败</div>
          <div className="error-state-desc">{error}</div>
        </div>
      </div>
    );
  }

  return <div ref={ref} style={{ width: "100%", height }} />;
}
