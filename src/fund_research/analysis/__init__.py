"""
Analysis layer — NAV metrics, holdings analysis, style/industry exposure, attribution.

Phase 1 scope (see requirements v0.4 section 12.1):
- nav_metrics: 收益风险指标（夏普、回撤、波动率等）
- holdings: 公开持仓分析（行业分布、市值分布、持仓变化）
- exposure: 风格/行业暴露（基于净值的回归暴露 + 基于持仓的真实暴露）
- attribution: 静态 Brinson 归因（使用披露持仓固定权重）

Phase 2+:
- simulated_holding: 模拟持仓（实验模块）
- dynamic_attribution: 动态收益拆解
- trading_ability: 交易能力分析
- scoring: 综合评分
- bond_factors: 债基因子暴露
"""
