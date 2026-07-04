"""
Fund similarity calculation — uses fingerprint vectors to find similar funds.

Supports five metric spaces (v0.4 §6.3.5):
- style: style_exposure + industry_exposure dimensions (cosine similarity)
- holding: industry distribution + holding overlap (Jaccard + cosine weighted)
- risk_return: return_risk dimension group (Euclidean distance, standardized)
- factor: alpha + style_exposure (Mahalanobis distance)
- composite: all dimensions weighted (weighted Euclidean)

Each result includes the top-3 contributing dimensions to explain WHY
two funds are similar.
"""

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.fingerprint import (
    fingerprint_to_dict,
)
from fund_research.db.models_phase3 import (
    FingerprintSimilarityCache,
    FundFingerprint,
)

ALGORITHM_NAME = "fund_similarity"
ALGORITHM_VERSION = "0.1.0"

# Metric space → dimension groups used
METRIC_SPACE_DIMENSIONS: dict[str, list[str]] = {
    "style": ["style_exposure", "industry_exposure"],
    "holding": ["industry_exposure", "holding_features"],
    "risk_return": ["return_risk"],
    "factor": ["alpha", "style_exposure"],
    "composite": [
        "return_risk",
        "style_exposure",
        "industry_exposure",
        "holding_features",
        "alpha",
        "scale",
        "team",
    ],
}


@dataclass
class SimilarityResult:
    """Similarity search result for a single fund pair."""

    fund_code: str
    similar_fund_code: str
    similarity_score: float
    metric_space: str
    contributing_dimensions: list[dict[str, Any]] = field(default_factory=list)

    def to_data(self) -> dict[str, Any]:
        return {
            "fund_code": self.fund_code,
            "similar_fund_code": self.similar_fund_code,
            "similarity_score": round(self.similarity_score, 4),
            "metric_space": self.metric_space,
            "contributing_dimensions": self.contributing_dimensions,
        }


def _extract_vector(
    fingerprint: FundFingerprint,
    dimension_groups: list[str],
) -> tuple[list[float], list[str]]:
    """Extract a flat numeric vector from fingerprint for given dimension groups.

    Returns (values, feature_names) where values may contain 0.0 for missing.
    """
    values: list[float] = []
    names: list[str] = []

    fp_vector: dict = fingerprint.vector or {}
    for group in dimension_groups:
        group_data = fp_vector.get(group, {})
        if isinstance(group_data, dict):
            for feat_name, feat_val in sorted(group_data.items()):
                if feat_val is not None:
                    values.append(float(feat_val))
                else:
                    values.append(0.0)
                names.append(f"{group}.{feat_name}")

    return values, names


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b:
        return 0.0
    arr_a = np.array(a)
    arr_b = np.array(b)
    norm_a = np.linalg.norm(arr_a)
    norm_b = np.linalg.norm(arr_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(arr_a, arr_b) / (norm_a * norm_b))


def _euclidean_distance(a: list[float], b: list[float]) -> float:
    """Standardized Euclidean distance, converted to similarity."""
    if not a or not b:
        return 0.0
    arr_a = np.array(a)
    arr_b = np.array(b)
    dist = float(np.linalg.norm(arr_a - arr_b))
    # Convert distance to similarity: sim = 1 / (1 + dist)
    return 1.0 / (1.0 + dist)


def _weighted_euclidean_similarity(
    a: list[float],
    b: list[float],
    weights: list[float] | None = None,
) -> float:
    """Weighted Euclidean distance converted to similarity."""
    if not a or not b:
        return 0.0
    arr_a = np.array(a)
    arr_b = np.array(b)
    w = np.array(weights) if weights else np.ones(len(a))
    diff = arr_a - arr_b
    dist = math.sqrt(float(np.sum(w * diff * diff)))
    return 1.0 / (1.0 + dist)


def _compute_contributions(
    target_vector: list[float],
    candidate_vector: list[float],
    feature_names: list[str],
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Compute per-dimension contribution to similarity.

    For each feature, contribution = 1 - |target_i - candidate_i| / (|target_i| + |candidate_i| + eps)
    """
    contributions = []
    for i, name in enumerate(feature_names):
        if i >= len(target_vector) or i >= len(candidate_vector):
            continue
        t = target_vector[i]
        c = candidate_vector[i]
        denom = abs(t) + abs(c) + 1e-8
        diff = abs(t - c)
        contrib = 1.0 - diff / denom
        contributions.append({"dimension": name, "contribution": round(contrib, 4)})

    # Sort by contribution descending, take top N
    contributions.sort(key=lambda x: x["contribution"], reverse=True)
    return contributions[:top_n]


def find_similar_funds(
    db: Session,
    fund_code: str,
    metric_space: str = "composite",
    top_n: int = 10,
    same_type_only: bool = True,
) -> list[SimilarityResult]:
    """Find similar funds using fingerprint vectors.

    Args:
        db: Database session
        fund_code: Target fund code
        metric_space: One of style/holding/risk_return/factor/composite
        top_n: Number of similar funds to return
        same_type_only: If True, only search within same fund_type

    Returns:
        List of SimilarityResult sorted by similarity_score descending
    """
    # Get target fingerprint
    target_fp = db.scalars(
        select(FundFingerprint)
        .where(FundFingerprint.fund_code == fund_code)
        .order_by(FundFingerprint.calc_date.desc())
        .limit(1)
    ).first()

    if target_fp is None:
        return []

    dimension_groups = METRIC_SPACE_DIMENSIONS.get(metric_space, METRIC_SPACE_DIMENSIONS["composite"])
    target_vector, feature_names = _extract_vector(target_fp, dimension_groups)

    if not target_vector:
        return []

    # Get candidate fingerprints (exclude target fund), cap at 2000 to prevent memory blowup
    query = (
        select(FundFingerprint)
        .where(FundFingerprint.fund_code != fund_code)
        .order_by(FundFingerprint.calc_date.desc())
        .limit(2000)
    )

    if same_type_only and target_fp.fund_type:
        query = query.where(FundFingerprint.fund_type == target_fp.fund_type)

    # Get latest fingerprint per fund (deduplicate)
    all_candidates = db.execute(query).scalars().all()
    seen_funds: set[str] = set()
    candidates: list[FundFingerprint] = []
    for fp in all_candidates:
        if fp.fund_code not in seen_funds:
            seen_funds.add(fp.fund_code)
            candidates.append(fp)

    results: list[SimilarityResult] = []

    for candidate in candidates:
        cand_vector, cand_names = _extract_vector(candidate, dimension_groups)

        # Use intersection of common features for distance computation
        if not cand_vector:
            continue
        cand_names_set = set(cand_names)
        common_names = [n for n in feature_names if n in cand_names_set]
        if not common_names:
            continue

        # Align vectors on common features
        common_target: list[float] = []
        common_cand: list[float] = []
        for name in common_names:
            t_idx = feature_names.index(name)
            c_idx = cand_names.index(name)
            if t_idx < len(target_vector) and c_idx < len(cand_vector):
                common_target.append(target_vector[t_idx])
                common_cand.append(cand_vector[c_idx])

        if not common_target:
            continue

        # Choose distance metric based on metric_space
        if metric_space in ("style", "holding"):
            score = _cosine_similarity(common_target, common_cand)
        elif metric_space == "risk_return" or metric_space == "factor":
            score = _euclidean_distance(common_target, common_cand)
        else:  # composite
            score = _weighted_euclidean_similarity(common_target, common_cand)

        if score <= 0:
            continue

        contributions = _compute_contributions(common_target, common_cand, common_names)

        results.append(
            SimilarityResult(
                fund_code=fund_code,
                similar_fund_code=candidate.fund_code,
                similarity_score=score,
                metric_space=metric_space,
                contributing_dimensions=contributions,
            )
        )

    # Sort by similarity descending, take top N
    results.sort(key=lambda x: x.similarity_score, reverse=True)
    return results[:top_n]


def compare_fund_fingerprints(
    db: Session,
    fund_codes: list[str],
) -> dict[str, Any]:
    """Compare fingerprints of multiple funds.

    Returns a comparison data structure with:
    - per-fund vector data
    - pairwise similarity matrix
    - holding overlap analysis
    """
    fingerprints: dict[str, FundFingerprint] = {}
    for code in fund_codes:
        fp = db.scalars(
            select(FundFingerprint)
            .where(FundFingerprint.fund_code == code)
            .order_by(FundFingerprint.calc_date.desc())
            .limit(1)
        ).first()
        if fp:
            fingerprints[code] = fp

    if len(fingerprints) < 2:
        return {
            "fund_codes": list(fingerprints.keys()),
            "comparison_data": {},
            "similarity_matrix": {},
            "warnings": ["需要至少 2 只有指纹的基金进行对比"],
        }

    # Build comparison data
    comparison_data: dict[str, Any] = {}
    for code, fp in fingerprints.items():
        comparison_data[code] = fingerprint_to_dict(fp)

    # Build pairwise similarity matrix (composite space)
    codes = list(fingerprints.keys())
    similarity_matrix: dict[str, dict[str, float]] = {}
    for i, code_a in enumerate(codes):
        similarity_matrix[code_a] = {}
        for j, code_b in enumerate(codes):
            if i == j:
                similarity_matrix[code_a][code_b] = 1.0
            elif j < i:
                similarity_matrix[code_a][code_b] = similarity_matrix[code_b][code_a]
            else:
                vec_a, names_a = _extract_vector(fingerprints[code_a], METRIC_SPACE_DIMENSIONS["composite"])
                vec_b, names_b = _extract_vector(fingerprints[code_b], METRIC_SPACE_DIMENSIONS["composite"])
                score = _weighted_euclidean_similarity(vec_a, vec_b) if names_a == names_b and vec_a and vec_b else 0.0
                similarity_matrix[code_a][code_b] = round(score, 4)

    # Holding overlap analysis
    overlap: dict[str, Any] = {}
    fp_vectors = {code: fp.vector or {} for code, fp in fingerprints.items()}
    for code_a in codes:
        hold_a = fp_vectors[code_a].get("holding_features", {})
        # We don't have stock-level overlap from fingerprint, but we can compare concentration metrics
        overlap[code_a] = {
            "top10_concentration": hold_a.get("top10_concentration"),
            "holding_count": hold_a.get("holding_count"),
        }

    return {
        "fund_codes": codes,
        "comparison_data": comparison_data,
        "similarity_matrix": similarity_matrix,
        "overlap_analysis": overlap,
    }


def persist_similarity_cache(
    db: Session,
    results: list[SimilarityResult],
    calc_date: date | None = None,
) -> None:
    """Persist similarity results to cache table."""
    if calc_date is None:
        calc_date = date.today()

    for result in results:
        # Check for existing
        existing = db.scalars(
            select(FingerprintSimilarityCache)
            .where(
                FingerprintSimilarityCache.fund_code == result.fund_code,
                FingerprintSimilarityCache.metric_space == result.metric_space,
                FingerprintSimilarityCache.similar_fund_code == result.similar_fund_code,
                FingerprintSimilarityCache.calc_date == calc_date,
            )
            .limit(1)
        ).first()

        if existing:
            existing.similarity_score = result.similarity_score
            existing.contributing_dimensions = result.contributing_dimensions
        else:
            db.add(
                FingerprintSimilarityCache(
                    fund_code=result.fund_code,
                    metric_space=result.metric_space,
                    similar_fund_code=result.similar_fund_code,
                    similarity_score=result.similarity_score,
                    contributing_dimensions=result.contributing_dimensions,
                    calc_date=calc_date,
                )
            )

    db.flush()
