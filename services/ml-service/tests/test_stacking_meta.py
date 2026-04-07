"""Tests for stacking meta-learner feature extraction and prediction."""
import pytest
import numpy as np

from app.forensics.base import AnalyzerFinding, ModuleResult, RiskLevel
from app.forensics.stacking_meta import (
    MODULE_ORDER,
    N_FEATURES,
    N_MODULES,
    extract_features,
    feature_names,
    reset_meta_learner,
    get_meta_learner,
)


# ---------------------------------------------------------------------------
# MODULE_ORDER integrity
# ---------------------------------------------------------------------------

def test_module_order_has_expected_modules():
    # 2026-04-07: Slimmed from 30 → 15 modules. Removed all permanently disabled
    # modules to make the meta-learner feature space tractable.
    # See stacking_meta.py MODULE_ORDER comment for full rationale.
    assert N_MODULES == 15, f"Expected 15 modules, got {N_MODULES}"


def test_module_order_contains_dinov2():
    assert "dinov2_ai_detection" in MODULE_ORDER


def test_module_order_contains_safe():
    assert "safe_ai_detection" in MODULE_ORDER


def test_module_order_no_duplicates():
    assert len(MODULE_ORDER) == len(set(MODULE_ORDER))


def test_module_order_matches_train_local():
    """MODULE_ORDER in stacking_meta.py must match train_local.py."""
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location(
        "train_local",
        os.path.join(os.path.dirname(__file__), "..", "scripts", "train_local.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    # Don't actually execute main(), just load the module-level constants
    # Read MODULE_ORDER directly from the file
    import ast
    script_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "train_local.py")
    with open(script_path) as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "MODULE_ORDER":
                    train_order = ast.literal_eval(node.value)
                    assert train_order == MODULE_ORDER, (
                        f"MODULE_ORDER mismatch between stacking_meta.py and train_local.py"
                    )
                    return
    pytest.fail("Could not find MODULE_ORDER in train_local.py")


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def test_extract_features_shape():
    modules = [
        ModuleResult(
            module_name="safe_ai_detection",
            module_label="SAFE",
            risk_score=0.60,
            risk_level=RiskLevel.HIGH,
            findings=[AnalyzerFinding(
                code="TEST", title="T", description="D",
                risk_score=0.60, confidence=0.80,
            )],
        )
    ]
    features = extract_features(modules)
    assert features.shape == (N_FEATURES,), f"Expected ({N_FEATURES},), got {features.shape}"


def test_extract_features_empty_modules():
    features = extract_features([])
    assert features.shape == (N_FEATURES,)
    assert np.all(features == 0.0)


def test_feature_names_count():
    names = feature_names()
    assert len(names) == N_FEATURES, f"Expected {N_FEATURES} names, got {len(names)}"


# ---------------------------------------------------------------------------
# Meta-learner prediction
# ---------------------------------------------------------------------------

def test_predict_returns_none_without_weights():
    """Without trained weights, predict() should return None (fallback signal)."""
    reset_meta_learner()
    meta = get_meta_learner("")
    modules = [
        ModuleResult(
            module_name="safe_ai_detection",
            module_label="SAFE",
            risk_score=0.50,
            risk_level=RiskLevel.HIGH,
        )
    ]
    result = meta.predict(modules)
    assert result is None


def test_predict_proba_returns_none_without_weights():
    reset_meta_learner()
    meta = get_meta_learner("")
    result = meta.predict_proba([])
    assert result is None
