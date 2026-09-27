"""Shared input hygiene for statement-based factors (plan 0015 Phase 3, ADR 0052).

Applied INSIDE each factor's _compute_scores, so the live signal step and the PIT
reconstruction (pit.py) — which call the same function with
as-of-sliced frames — see identically cleaned inputs. Before this, the filters
lived only in each module's live `_load_data`, and the backtest measured a
slightly different factor (piotroski: 819 of 2,220 overlapping rows differed).
"""
from config import SCREEN

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])


def prefer_consolidated(qi):
    """Consolidated rows where a sid has any, standalone otherwise. Idempotent."""
    if qi is None or qi.empty or "reporting" not in qi.columns:
        return qi
    has_consol = set(qi.loc[qi["reporting"] == "consolidated", "sid"])
    keep = (qi["sid"].isin(has_consol) & (qi["reporting"] == "consolidated")) | ~qi["sid"].isin(has_consol)
    return qi[keep]


def without_financials(stocks):
    """Drop Financials (structurally N/A for bank balance sheets; ADR 0048)."""
    if "sector" not in stocks.columns:
        return stocks
    return stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)]
