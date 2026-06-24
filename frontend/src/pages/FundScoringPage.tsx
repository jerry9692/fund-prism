import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type FundScoreItem } from "../api/client";
import ChartWrapper from "../components/ChartWrapper";
import MetricCard from "../components/MetricCard";

const DIM_LABELS: Record<string, string> = {
  return: "收益能力",
  risk: "风险控制",
  alpha: "Alpha 能力",
  trading: "交易能力",
  style_stability: "风格稳定性",
  scale: "规模适配",
  team: "团队稳定性",
  holder: "持有人稳定性",
};

const PRESET_OPTIONS = ["均衡型", "稳健型", "进取型"];

export default function FundScoringPage() {
  const { code } = useParams<{ code: string }>();
  const [scores, setScores] = useState<FundScoreItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [scoreVersion, setScoreVersion] = useState<string | null>(null);

  // Run scoring form
  const [fundCodes, setFundCodes] = useState(code || "");
  const [preset, setPreset] = useState("均衡型");
  const [running, setRunning] = useState(false);

  // If navigated from fund detail, auto-run scoring for that fund
  useEffect(() => {
    if (code) {
      setFundCodes(code);
      runScoring(code);
    }
  }, [code]);

  async function runScoring(codes?: string) {
    const codesStr = (codes || fundCodes).trim();
    if (!codesStr) return;

    setRunning(true);
    setErrorMessage(null);
    try {
      const body = await api.runScoring({
        fund_codes: codesStr.split(",").map((s) => s.trim()).filter(Boolean),
        preset,
      });
      if (body.data === null) {
        setErrorMessage(body.warnings.join("; ") || "评分失败");
        return;
      }
      setScores(body.data.fund_scores ?? []);
      setScoreVersion(body.data.score_version);
    } catch (e) {
      setErrorMessage(`评分异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRunning(false);
      setLoading(false);
    }
  }

  // Load latest score for this fund on initial mount
  useEffect(() => {
    if (!code) {
      setLoading(false);
      return;
    }
    // auto-run handles loading
  }, []);

  const fundScore = scores.find((s) => s.fund_code === code) || scores[0];

  return (
    <div className="experiments-page">
      <div className="page-header">
        <div>
          <h1>综合评分</h1>
          {scoreVersion && (
            <div className="summary-row">
              <span className="mono-cell">版本: {scoreVersion}</span>
              <span>{scores.length} 只基金</span>
            </div>
          )}
        </div>
      </div>

      {errorMessage && (
        <div className="card error-banner">
          <span>{errorMessage}</span>
          <button className="button-ghost" onClick={() => setErrorMessage(null)}>关闭</button>
        </div>
      )}

      {/* Run form — always show when not on a specific fund, or no results yet */}
      {(!code || (!loading && !fundScore)) && (
        <div className="card experiment-form" style={{ marginBottom: 16 }}>
          <div className="form-row" style={{ flexWrap: "wrap", gap: 12 }}>
            <label><span>基金代码</span>
              <input value={fundCodes}
                     onChange={(e) => setFundCodes(e.target.value)}
                     placeholder="000001,163406"
                     style={{ width: 180 }} />
            </label>
            <label><span>评分预设</span>
              <select value={preset} onChange={(e) => setPreset(e.target.value)}>
                {PRESET_OPTIONS.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </label>
            <button className="button-primary" onClick={() => runScoring()} disabled={running}>
              {running ? "评分中..." : "运行评分"}
            </button>
          </div>
        </div>
      )}

      {loading ? <p>加载中...</p> : !fundScore ? (
        <div className="card empty-state">
          {code ? `基金 ${code} 暂无评分数据` : "输入基金代码并点击运行评分"}
        </div>
      ) : (
        <div>
          {/* Fund score summary cards */}
          <div className="metric-grid" style={{ marginBottom: 16 }}>
            <MetricCard
              label="综合评分"
              value={fundScore.total_score.toFixed(1)}
              unit="/ 100"
              conclusionStatus={fundScore.contains_estimated ? "observation" : "computed"}
              hint={fundScore.contains_estimated ? "含估计成分" : "全量计算"}
            />
            <MetricCard
              label="同类排名"
              value={`前 ${(fundScore.percentile_rank * 100).toFixed(0)}%`}
              conclusionStatus="computed"
            />
            <MetricCard
              label="评分版本"
              value={scoreVersion || "—"}
              conclusionStatus="fact"
            />
            <MetricCard
              label="扣分项"
              value={fundScore.deduction_reasons.length}
              unit="项"
              conclusionStatus={fundScore.deduction_reasons.length > 0 ? "needs_review" : "computed"}
              hint={fundScore.deduction_reasons.length > 0 ? fundScore.deduction_reasons.join("; ") : "无扣分"}
            />
          </div>

          {/* Sub-scores bar chart via ChartWrapper */}
          <ChartWrapper
            type="bar"
            title="维度子评分"
            labels={Object.entries(fundScore.sub_scores)
              .sort(([, a], [, b]) => b - a)
              .map(([dim]) => DIM_LABELS[dim] || dim)}
            series={[{
              label: "子评分",
              values: Object.entries(fundScore.sub_scores)
                .sort(([, a], [, b]) => b - a)
                .map(([, score]) => score),
            }]}
            yLabel="评分"
            formatY={(v) => v.toFixed(0)}
            height={280}
          />

          {/* All scored funds ranking table */}
          {scores.length > 1 && (
            <div className="card table-card">
              <h3 style={{ marginTop: 0 }}>评分排名</h3>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>排名</th><th>基金代码</th><th>总分</th>
                    <th>分位数</th><th>含估计</th><th>扣分项</th>
                  </tr>
                </thead>
                <tbody>
                  {scores.map((s, i) => (
                    <tr key={s.fund_code}
                        className={s.fund_code === code ? "selected-row" : ""}>
                      <td>{i + 1}</td>
                      <td className="mono-cell">{s.fund_code}</td>
                      <td className="mono-cell">{s.total_score.toFixed(1)}</td>
                      <td>前 {(s.percentile_rank * 100).toFixed(0)}%</td>
                      <td>
                        {s.contains_estimated
                          ? <span className="badge badge-observation">是</span>
                          : <span className="badge badge-computed">否</span>}
                      </td>
                      <td style={{ fontSize: 12, maxWidth: 250 }}>
                        {s.deduction_reasons.length > 0
                          ? s.deduction_reasons.join("; ")
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
