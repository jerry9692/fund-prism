/**
 * NavIcon — 侧边栏图标系统
 *
 * 设计语言：极简线性 / 1.5px 描边 / 24×24 viewBox / currentColor
 * 风格统一性高于装饰性，适合金融研究工具的克制气质。
 * 每个图标都根据语义定制形状，非通用符号堆砌。
 */

import type { JSX } from "react";

const PATHS: Record<string, JSX.Element> = {
  // ---- 工作台 ----
  // 雷达扫描：中心点 + 扫描线，表达"研究/侦测"
  radar: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
      <path d="M12 12 L19.5 7.5" />
    </>
  ),

  // ---- 基金研究 ----
  // 漏斗：筛选语义
  filter: (
    <>
      <path d="M4 5 H20 L14 13 V19 L10 21 V13 Z" />
    </>
  ),
  // 书签：收藏池
  bookmark: (
    <>
      <path d="M7 4 H17 V20 L12 16 L7 20 Z" />
    </>
  ),
  // 指纹：同心椭圆纹路 + 偏心中心 + 断口（真实指纹特征）
  fingerprint: (
    <>
      {/* 外圈纹路（顶部断口） */}
      <path d="M6.5 12 a5.5 6 0 1 1 11 0 v3 a5.5 6 0 1 1 -11 0 Z" strokeOpacity="0.9" />
      {/* 中圈纹路（左侧断口） */}
      <path d="M9 12.5 a3 3.5 0 1 1 6 0 v2.5" strokeOpacity="0.75" />
      {/* 内圈纹路 */}
      <path d="M10.8 12.5 a1.2 1.5 0 1 1 2.4 0 v1.5" strokeOpacity="0.6" />
      {/* 中心点 */}
      <circle cx="12" cy="12.8" r="0.7" fill="currentColor" stroke="none" />
    </>
  ),
  // 相似搜索：两圆相交（交集即相似度）
  similar: (
    <>
      <circle cx="9" cy="12" r="6" />
      <circle cx="15" cy="12" r="6" />
    </>
  ),
  // 对比：两根不同高度柱子
  compare: (
    <>
      <path d="M7 20 V11 M5 11 H9 M5 20 H9" />
      <path d="M17 20 V5 M15 5 H19 M15 20 H19" />
    </>
  ),

  // ---- 发现与反选 ----
  // 异常：三角警告 + 感叹点
  alert: (
    <>
      <path d="M12 4 L21 20 H3 Z" />
      <path d="M12 10 V14" />
      <circle cx="12" cy="17.2" r="0.6" fill="currentColor" stroke="none" />
    </>
  ),
  // 反选：双向箭头
  reverse: (
    <>
      <path d="M9 8 L4 12 L9 16" />
      <path d="M15 8 L20 12 L15 16" />
      <path d="M4 12 H20" />
    </>
  ),
  // 模板：4格网格
  grid: (
    <>
      <rect x="4" y="4" width="7" height="7" rx="1" />
      <rect x="13" y="4" width="7" height="7" rx="1" />
      <rect x="4" y="13" width="7" height="7" rx="1" />
      <rect x="13" y="13" width="7" height="7" rx="1" />
    </>
  ),
  // 归档盒：箱体 + 顶盖 + 标签线
  archive: (
    <>
      <path d="M4 8 V20 H20 V8" />
      <path d="M3 4 H21 V8 H3 Z" />
      <path d="M10 12 H14" />
    </>
  ),

  // ---- 算法实验 ----
  // 烧瓶：实验语义
  flask: (
    <>
      <path d="M10 3 H14 V9 L18.5 19 H5.5 L10 9 Z" />
      <path d="M8 3 H16" />
      <path d="M8 14 H16" strokeOpacity="0.5" strokeDasharray="2 2" />
    </>
  ),
  // 验收徽章：圆 + 勾 + 丝带
  certificate: (
    <>
      <circle cx="12" cy="9" r="6" />
      <path d="M9.5 9 L11.2 10.8 L14.5 7.2" />
      <path d="M8 14 L8 21 L12 19 L16 21 L16 14" />
    </>
  ),
  // 回测：时钟 + 逆时针箭头
  backtest: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8 V12 L15 14" />
      <path d="M5 9 L5 5 L9 5" strokeOpacity="0.6" />
    </>
  ),

  // ---- 系统 ----
  // 数据质量：盾牌 + 勾
  shieldCheck: (
    <>
      <path d="M12 3 L20 6 V12 C20 16.5 16 20 12 21 C8 20 4 16.5 4 12 V6 Z" />
      <path d="M9 12 L11.2 14.2 L15 10" />
    </>
  ),
  // 证据链：两段链
  link: (
    <>
      <path d="M10 8 H8 A4 4 0 1 0 8 16 H10" />
      <path d="M14 8 H16 A4 4 0 1 1 16 16 H14" />
      <path d="M10 12 H14" />
    </>
  ),
  // API 调试：终端框 + > 提示符 + 光标
  terminal: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M7 10 L10 12.5 L7 15" />
      <path d="M13 15 H17" />
    </>
  ),

  // ---- 基金详情子菜单 ----
  // 概览：信息圆
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11 V17" />
      <circle cx="12" cy="7.8" r="0.6" fill="currentColor" stroke="none" />
    </>
  ),
  // 持仓分析：饼图切片
  pie: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 3 V12 H21" />
    </>
  ),
  // 风格与归因：阶梯瀑布（归因分解）
  waterfall: (
    <>
      <path d="M4 4 V20 H20" strokeOpacity="0.45" />
      <path d="M6 18 V14 H10 V10 H14 V6 H18" />
    </>
  ),
  // 评分：五角星
  star: (
    <>
      <path d="M12 3 L14.5 9 L21 9.5 L16 14 L17.5 20.5 L12 17 L6.5 20.5 L8 14 L3 9.5 L9.5 9 Z" />
    </>
  ),
  // 研究输出：文档
  fileText: (
    <>
      <path d="M6 3 H14 L19 8 V21 H6 Z" />
      <path d="M14 3 V8 H19" />
      <path d="M9 13 H16" />
      <path d="M9 17 H16" />
    </>
  ),
  // 校验：勾选框
  checkSquare: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M8 12 L11 15 L16 9" />
    </>
  ),
};

export type NavIconName = keyof typeof PATHS;

interface NavIconProps {
  name: string;
  size?: number;
  className?: string;
}

export function NavIcon({ name, size = 18, className }: NavIconProps) {
  const path = PATHS[name];
  if (!path) {
    // 未知图标：渲染一个空心圆作为兜底，避免空白
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={className}
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="8" />
      </svg>
    );
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {path}
    </svg>
  );
}
