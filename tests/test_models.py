"""Tests for the unified model registry (backend/models.py).

These guard the single-source-of-truth contract: every selectable model has
metadata + pricing, ALLOWED_MODELS stays in sync with MODELS, and calc_cost is
monotonic in token counts.
"""
from backend.models import (
    ALLOWED_MODELS,
    DEFAULT_MODEL,
    MODELS,
    UTILITY_MODEL,
    calc_cost,
)


def test_allowed_models_matches_registry():
    """ALLOWED_MODELS must be exactly the keys of MODELS."""
    assert ALLOWED_MODELS == set(MODELS.keys())


def test_default_model_is_registered():
    assert DEFAULT_MODEL in MODELS


def test_utility_model_is_registered():
    assert UTILITY_MODEL in MODELS


def test_every_model_has_pricing():
    """No model should be selectable without pricing data."""
    for model_id, config in MODELS.items():
        p_in, p_out = config.pricing()
        assert p_in >= 0, f"{model_id} has negative input price"
        assert p_out >= 0, f"{model_id} has negative output price"


def test_calc_cost_scales_with_tokens():
    """Doubling tokens should not decrease cost."""
    cheap = calc_cost(DEFAULT_MODEL, 100, 100)
    pricey = calc_cost(DEFAULT_MODEL, 200, 200)
    assert pricey >= cheap


def test_calc_cost_zero_tokens_is_zero():
    assert calc_cost(DEFAULT_MODEL, 0, 0) == 0.0


def test_calc_cost_unknown_model_uses_fallback():
    """Unknown models fall back to a non-zero estimate rather than crashing."""
    cost = calc_cost("does-not-exist", 1000, 1000)
    assert cost > 0


def test_calc_cost_handles_negative_tokens():
    """Negative token counts are clamped to zero (defensive)."""
    assert calc_cost(DEFAULT_MODEL, -100, -100) == 0.0