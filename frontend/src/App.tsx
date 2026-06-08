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
          <Route path="/data-quality" element={<DataQualityPage />} />
        </Routes>
      </main>
      <DisclaimerFooter />
    </div>
  );
}
