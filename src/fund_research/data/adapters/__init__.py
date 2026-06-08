"""Data source adapters — pluggable interfaces for different data providers."""

from fund_research.data.adapters.akshare import AkshareAdapter
from fund_research.data.adapters.base import BaseDataAdapter, FetchResult

__all__ = ["AkshareAdapter", "BaseDataAdapter", "FetchResult"]
