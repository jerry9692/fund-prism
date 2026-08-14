"""Same-category ranking (requirements v0.4 §6.1.4.2 / §6.1.4.5).

Computes ``k/N`` ranks and percentiles for a metric within each fund
``sub_category`` group, mirroring the legacy ``GetRankInType`` semantics so
filter/compare pages and the scoring layer can share one ranking口径.

Ranking convention (matches ``pandas.Series.rank``):
- ``ascending=False`` (default): the **highest** metric value gets rank 1
  (use for return / Sharpe / Calmar / drawdown where less-negative is better).
- ``ascending=True``: the **lowest** metric value gets rank 1
  (use for volatility / max_drawdown magnitude / tracking error).

Ties use competition ranking (``method='min'``): tied funds share the same
``k`` and the next rank skips (e.g. two funds tied at rank 1 → next fund is
rank 3). Percentile is derived from the rank so tied funds share it too.

Edge cases:
- Group with a single fund → ``rank=1``, ``total=1``, ``percentile=None``
  (undefined), ``rank_text='1/1'``.
- Funds with a missing (NaN) metric value are excluded from the group before
  ranking and receive ``rank=None`` / ``percentile=None`` in the output.
"""

from dataclasses import dataclass

import pandas as pd

ALGORITHM_NAME = "rank_in_category"
ALGORITHM_VERSION = "0.1.0"


@dataclass
class CategoryRank:
    """Rank of a single fund within its sub_category group."""

    fund_code: str
    sub_category: str | None
    metric_value: float | None
    rank: int | None
    total: int
    percentile: float | None
    rank_text: str

    def to_data(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "sub_category": self.sub_category,
            "metric_value": self.metric_value,
            "rank": self.rank,
            "total": self.total,
            "percentile": self.percentile,
            "rank_text": self.rank_text,
        }


def rank_in_category(
    values: dict[str, float],
    fund_code: str,
    *,
    ascending: bool = False,
    sub_category: str | None = None,
) -> CategoryRank | None:
    """Rank a single fund against its peers on one metric.

    Parameters
    ----------
    values
        ``{fund_code: metric_value}`` for every fund in the same category.
        NaN entries are dropped before ranking.
    fund_code
        The fund to rank. Returns ``None`` if absent from ``values``.
    ascending
        ``False`` (default) → highest value is best (rank 1).
        ``True`` → lowest value is best (rank 1).
    sub_category
        Optional label carried through to the result for context.

    Returns
    -------
    CategoryRank | None
    """
    if fund_code not in values:
        return None

    target_value = values[fund_code]
    series = pd.Series(values, dtype="float64").dropna()
    total = int(len(series))
    if total == 0 or pd.isna(target_value):
        return CategoryRank(
            fund_code=fund_code,
            sub_category=sub_category,
            metric_value=None if pd.isna(target_value) else float(target_value),
            rank=None,
            total=total,
            percentile=None,
            rank_text=f"-/{total}" if total else "-/0",
        )

    ranks = series.rank(ascending=ascending, method="min").astype(int)
    rank = int(ranks.loc[fund_code])
    percentile = (total - rank) / (total - 1) if total > 1 else None
    return CategoryRank(
        fund_code=fund_code,
        sub_category=sub_category,
        metric_value=float(target_value),
        rank=rank,
        total=total,
        percentile=round(float(percentile), 6) if percentile is not None else None,
        rank_text=f"{rank}/{total}",
    )


def compute_category_ranks(
    funds_df: pd.DataFrame,
    metric_column: str,
    *,
    group_column: str = "sub_category",
    ascending: bool = False,
) -> pd.DataFrame:
    """Compute ``k/N`` rank + percentile for every fund within its category.

    Parameters
    ----------
    funds_df
        DataFrame with at least ``fund_code``, ``group_column`` and
        ``metric_column``. Rows with NaN metric are kept in the output but
        receive ``rank=None`` / ``percentile=None``.
    metric_column
        Column to rank on.
    group_column
        Column defining the peer group (default ``sub_category``).
    ascending
        ``False`` (default) → highest value is best. ``True`` → lowest is best.

    Returns
    -------
    DataFrame[fund_code, <group_column>, <metric_column>, rank, total,
              percentile, rank_text]
    """
    required = {"fund_code", group_column, metric_column}
    missing = required - set(funds_df.columns)
    if missing:
        raise ValueError(f"funds_df 缺少列: {sorted(missing)}")

    if funds_df.empty:
        return pd.DataFrame(
            columns=["fund_code", group_column, metric_column, "rank", "total", "percentile", "rank_text"]
        )

    data = funds_df.copy()
    data[metric_column] = pd.to_numeric(data[metric_column], errors="coerce")

    rows: list[dict] = []
    for group_key, group in data.groupby(group_column, dropna=False):
        values = pd.to_numeric(group[metric_column], errors="coerce")
        valid = values.dropna()
        total = int(len(valid))
        if total == 0:
            rank_series = pd.Series([pd.NA] * len(group), index=group.index)
        else:
            rank_series = values.rank(ascending=ascending, method="min")

        for idx, row in group.iterrows():
            metric_val = values.loc[idx]
            rank_val = rank_series.loc[idx]
            if pd.isna(metric_val) or pd.isna(rank_val):
                rank_int: int | None = None
                percentile: float | None = None
                rank_text = f"-/{total}" if total else "-/0"
            else:
                rank_int = int(rank_val)
                percentile = (
                    round(float((total - rank_int) / (total - 1)), 6)
                    if total > 1
                    else None
                )
                rank_text = f"{rank_int}/{total}"
            rows.append({
                "fund_code": row["fund_code"],
                group_column: group_key,
                metric_column: float(metric_val) if pd.notna(metric_val) else None,
                "rank": rank_int,
                "total": total,
                "percentile": percentile,
                "rank_text": rank_text,
            })

    result_df = pd.DataFrame(
        rows,
        columns=["fund_code", group_column, metric_column, "rank", "total", "percentile", "rank_text"],
    )
    # Use nullable dtypes so missing ranks/percentiles are <NA> rather than
    # NaN — keeps the column typed as integer and lets downstream code
    # distinguish "no rank" from a valid rank.
    result_df["rank"] = result_df["rank"].astype("Int64")
    result_df["total"] = result_df["total"].astype("Int64")
    result_df["percentile"] = result_df["percentile"].astype("Float64")
    return result_df
