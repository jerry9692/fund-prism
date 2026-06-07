"""
Research layer — Research Packet generation, Evidence chain, Confidence scoring.

Core components (Phase 1):
- packet: Research Packet 生成（单只基金体检 + 结构化 JSON/Markdown）
- evidence: Evidence 证据链（结论追溯、来源引用）
- confidence: 结论可信度门禁（数据完整度、来源等级、模型适用性检查）
"""

from fund_research.research.packet import build_single_fund_packet, persist_research_packet

__all__ = ["build_single_fund_packet", "persist_research_packet"]
