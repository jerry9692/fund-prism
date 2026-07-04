// 顶层错误边界 — 捕获渲染异常，防止白屏
// variant="page" (默认): 居中大块错误提示
// variant="inline": 轻量错误卡片，适用于路由段

import { Component, type ErrorInfo, type ReactNode } from "react";

type ErrorBoundaryVariant = "page" | "inline";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  variant?: ErrorBoundaryVariant;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("[ErrorBoundary] 渲染异常:", error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      const variant = this.props.variant ?? "page";

      if (variant === "inline") {
        return (
          <div className="route-error-boundary">
            <div className="route-error-icon">!</div>
            <div className="route-error-body">
              <div className="route-error-title">该模块加载出错</div>
              <div className="route-error-msg">
                {this.state.error?.message ?? "发生了未知错误"}
              </div>
            </div>
            <button className="btn btn-secondary btn-sm" onClick={this.handleRetry}>
              重试
            </button>
          </div>
        );
      }

      // page variant (default)
      return (
        <div className="page-error-boundary">
          <h2 className="page-error-title">页面加载出错</h2>
          <p className="page-error-desc">
            {this.state.error?.message ?? "发生了未知错误"}
          </p>
          <div className="page-error-stack">
            {this.state.error?.stack?.split("\n").slice(0, 8).map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
          <div className="page-error-actions">
            <button
              className="btn btn-primary"
              onClick={this.handleRetry}
            >
              重试
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => (window.location.href = "/")}
            >
              返回首页
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// ---- RouteErrorBoundary: 轻量级路由段错误边界 ----

export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  return (
    <ErrorBoundary variant="inline">{children}</ErrorBoundary>
  );
}
