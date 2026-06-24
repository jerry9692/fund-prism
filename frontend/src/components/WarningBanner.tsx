/**
 * WarningBanner — reusable warning/alert banner.
 * Acceptance criterion §4.3: WarningBanner for data-missing / estimated /
 * low-confidence warnings.
 */

import type { ReactNode } from "react";

export type WarningLevel = "info" | "warning" | "danger";

export interface WarningBannerProps {
  level?: WarningLevel;
  children: ReactNode;
  dismissible?: boolean;
  onDismiss?: () => void;
}

const LEVEL_STYLES: Record<WarningLevel, { bg: string; color: string }> = {
  info: { bg: "var(--color-primary-light)", color: "var(--color-primary)" },
  warning: { bg: "var(--color-warning-light)", color: "var(--color-warning)" },
  danger: { bg: "var(--color-danger-light)", color: "var(--color-danger)" },
};

export default function WarningBanner({
  level = "warning",
  children,
  dismissible = false,
  onDismiss,
}: WarningBannerProps) {
  const style = LEVEL_STYLES[level];
  return (
    <div
      className="warning-banner"
      style={{
        background: style.bg,
        color: style.color,
        padding: "12px 16px",
        borderRadius: "var(--radius-md)",
        marginBottom: "var(--space-md)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "var(--space-md)",
      }}
    >
      <div>{children}</div>
      {dismissible && onDismiss && (
        <button
          onClick={onDismiss}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: 18,
            color: style.color,
          }}
          aria-label="关闭"
        >
          ×
        </button>
      )}
    </div>
  );
}
