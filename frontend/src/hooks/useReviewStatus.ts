/**
 * useReviewStatus — lightweight hook to load a fund's review status.
 * Returns is_excluded flag and loading state.
 * Used by fund detail / analysis pages to apply visual downgrade.
 */
import { useEffect, useState } from "react";
import { api } from "../api/client";

export interface ReviewStatusInfo {
  is_excluded: boolean;
  is_locked: boolean;
  is_approved: boolean;
  loading: boolean;
}

export function useReviewStatus(fundCode?: string): ReviewStatusInfo {
  const [state, setState] = useState<ReviewStatusInfo>({
    is_excluded: false,
    is_locked: false,
    is_approved: false,
    loading: true,
  });

  useEffect(() => {
    if (!fundCode) {
      setState((s) => ({ ...s, loading: false }));
      return;
    }
    let cancelled = false;
    api
      .getFundReviewStatus(fundCode)
      .then((res) => {
        if (cancelled) return;
        const data = res.data;
        setState({
          is_excluded: Boolean(data?.is_excluded),
          is_locked: Boolean(data?.is_locked),
          is_approved: Boolean(data?.is_approved),
          loading: false,
        });
      })
      .catch(() => {
        if (cancelled) return;
        setState((s) => ({ ...s, loading: false }));
      });
    return () => {
      cancelled = true;
    };
  }, [fundCode]);

  return state;
}
