import { Routes, Route } from "react-router-dom";
import NavBar from "./components/NavBar";
import DisclaimerFooter from "./components/DisclaimerFooter";
import HomePage from "./pages/HomePage";
import FundListPage from "./pages/FundListPage";
import FundDetailPage from "./pages/FundDetailPage";
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

export default function App() {
  return (
    <div>
      <NavBar />
      <main className="page-container">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/funds" element={<FundListPage />} />
          <Route path="/funds/:code" element={<FundDetailPage />} />
          <Route path="/funds/:code/holdings" element={<HoldingsPage />} />
          <Route path="/funds/:code/exposure" element={<ExposurePage />} />
          <Route path="/funds/:code/packet" element={<ResearchPacketPage />} />
          <Route path="/funds/:code/diff" element={<PacketDiffPage />} />
          <Route path="/funds/:code/scoring" element={<FundScoringPage />} />
          <Route path="/funds/:code/simulated" element={<SimulatedHoldingPage />} />
          <Route path="/funds/:code/attribution" element={<DynamicAttributionPage />} />
          <Route path="/funds/:code/review" element={<FundReviewPage />} />
          <Route path="/data-quality" element={<DataQualityPage />} />
          <Route path="/experiments" element={<ExperimentsPage />} />
          <Route path="/experiments/p2b-report" element={<P2BValidationPage />} />
          <Route path="/scoring/backtest" element={<ScoringBacktestPage />} />
        </Routes>
      </main>
      <DisclaimerFooter />
    </div>
  );
}
