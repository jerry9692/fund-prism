import { Routes, Route } from "react-router-dom";
import AppShell from "./components/shell/AppShell";
import HomePage from "./pages/HomePage";
import FundListPage from "./pages/FundListPage";
import FundDetailLayout from "./pages/FundDetailLayout";
import FundOverviewPage from "./pages/FundOverviewPage";
import HoldingsPage from "./pages/HoldingsPage";
import ExposurePage from "./pages/ExposurePage";
import ResearchPacketPage from "./pages/ResearchPacketPage";
import PacketDiffPage from "./pages/PacketDiffPage";
import DataQualityPage from "./pages/DataQualityPage";
import ExperimentsPage from "./pages/ExperimentsPage";
import P2BValidationPage from "./pages/P2BValidationPage";
import ScoringBacktestPage from "./pages/ScoringBacktestPage";
import FundScoringPage from "./pages/FundScoringPage";
import FundReviewPage from "./pages/FundReviewPage";
import SimulatedHoldingPage from "./pages/SimulatedHoldingPage";
import DynamicAttributionPage from "./pages/DynamicAttributionPage";
import EvidencePage from "./pages/EvidencePage";
import ApiDebugPage from "./pages/ApiDebugPage";
import FundPoolPage from "./pages/FundPoolPage";
import ReverseLookupPage from "./pages/ReverseLookupPage";
import TemplateListPage from "./pages/TemplateListPage";
import SimilarFundsPage from "./pages/SimilarFundsPage";
import FingerprintPage from "./pages/FingerprintPage";
import FundComparePage from "./pages/FundComparePage";
import AnomalyListPage from "./pages/AnomalyListPage";
import AnomalyDetailPage from "./pages/AnomalyDetailPage";
import ResearchPacketListPage from "./pages/ResearchPacketListPage";
import ResearchPacketDetailPage from "./pages/ResearchPacketDetailPage";
import ErrorBoundary, { RouteErrorBoundary } from "./components/ErrorBoundary";

export default function App() {
  return (
    <AppShell>
      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/funds" element={<FundListPage />} />

          {/* 基金详情嵌套路由：Layout 包含面包屑+标题+TabNav，Outlet 渲染子页面 */}
          <Route path="/funds/:code" element={<FundDetailLayout />}>
            <Route index element={<RouteErrorBoundary><FundOverviewPage /></RouteErrorBoundary>} />
            <Route path="holdings" element={<RouteErrorBoundary><HoldingsPage /></RouteErrorBoundary>} />
            <Route path="exposure" element={<RouteErrorBoundary><ExposurePage /></RouteErrorBoundary>} />
            <Route path="packet" element={<RouteErrorBoundary><ResearchPacketPage /></RouteErrorBoundary>} />
            <Route path="diff" element={<RouteErrorBoundary><PacketDiffPage /></RouteErrorBoundary>} />
            <Route path="scoring" element={<RouteErrorBoundary><FundScoringPage /></RouteErrorBoundary>} />
            <Route path="simulated" element={<RouteErrorBoundary><SimulatedHoldingPage /></RouteErrorBoundary>} />
            <Route path="attribution" element={<RouteErrorBoundary><DynamicAttributionPage /></RouteErrorBoundary>} />
            <Route path="similar" element={<RouteErrorBoundary><SimilarFundsPage /></RouteErrorBoundary>} />
            <Route path="review" element={<RouteErrorBoundary><FundReviewPage /></RouteErrorBoundary>} />
          </Route>

          <Route path="/fund-pool" element={<FundPoolPage />} />
          <Route path="/data-quality" element={<DataQualityPage />} />
          <Route path="/evidence" element={<EvidencePage />} />
          <Route path="/api-debug" element={<ApiDebugPage />} />
          <Route path="/experiments" element={<ExperimentsPage />} />
          <Route path="/experiments/p2b-report" element={<P2BValidationPage />} />
          <Route path="/scoring/backtest" element={<ScoringBacktestPage />} />
          <Route path="/reverse-lookup" element={<ReverseLookupPage />} />
          <Route path="/templates" element={<TemplateListPage />} />
          <Route path="/similar-funds" element={<SimilarFundsPage />} />
          <Route path="/fingerprint" element={<FingerprintPage />} />
          <Route path="/fund-compare" element={<FundComparePage />} />
          <Route path="/anomalies" element={<AnomalyListPage />} />
          <Route path="/anomalies/:id" element={<RouteErrorBoundary><AnomalyDetailPage /></RouteErrorBoundary>} />
          <Route path="/research-packets" element={<RouteErrorBoundary><ResearchPacketListPage /></RouteErrorBoundary>} />
          <Route path="/research-packets/:id" element={<RouteErrorBoundary><ResearchPacketDetailPage /></RouteErrorBoundary>} />
        </Routes>
      </ErrorBoundary>
    </AppShell>
  );
}
