"""Tests for the extracted post-fuse gate function.

Locks in the operator-semantic convention (`<=` rejects, threshold values are
themselves rejected) via boundary parametrize tests at exactly the seam.
A mutation that flipped `<=` to `<` would fail these tests immediately.
"""

import pytest

from lost_landscapes.detection.postprocess.post_fuse_gate import apply_post_fuse_gate
from tests.conftest import make_candidate

# ===== T1.1 — make_candidate factory behavior =====

def test_make_candidate_omits_shape_keys_when_none():
    """When elongation/circularity are None, the keys are absent from morphometrics.

    This is load-bearing: the gate's default-fallback behavior at line "elongation"
    in apply_post_fuse_gate depends on the key being absent (not 0.0) for ML/no-outline
    candidates.
    """
    c = make_candidate(elongation=None, circularity=None)
    assert "elongation" not in c.morphometrics
    assert "circularity" not in c.morphometrics


def test_make_candidate_includes_shape_keys_when_set():
    c = make_candidate(elongation=0.6, circularity=0.4)
    assert c.morphometrics["elongation"] == 0.6
    assert c.morphometrics["circularity"] == 0.4


# ===== T2.1 — Boundary parametrize at exact thresholds (mutation-grade) =====

@pytest.mark.parametrize("elongation,expected_kept", [
    (0.39999, False),  # below threshold → rejected
    (0.40000, False),  # AT threshold → rejected (locked: <= rejects)
    (0.40001, True),   # just above → kept
    (1.0, True),       # round → kept
])
def test_apply_post_fuse_gate_elongation_seam(elongation, expected_kept):
    c = make_candidate(elongation=elongation, circularity=0.5)
    survivors = apply_post_fuse_gate([c])
    assert (c in survivors) is expected_kept, (
        f"elongation={elongation}: expected_kept={expected_kept}, got {c in survivors}"
    )


@pytest.mark.parametrize("circularity,expected_kept", [
    (0.29999, False),
    (0.30000, False),
    (0.30001, True),
    (1.0, True),
])
def test_apply_post_fuse_gate_circularity_seam(circularity, expected_kept):
    c = make_candidate(elongation=0.5, circularity=circularity)
    survivors = apply_post_fuse_gate([c])
    assert (c in survivors) is expected_kept


# ===== T1.3 — Default-fallback when shape keys absent =====

def test_apply_post_fuse_gate_keeps_candidate_without_shape_keys():
    """ML/point-cloud / no-outline candidates lack elongation/circularity → default 1.0 → keep."""
    c = make_candidate(elongation=None, circularity=None)
    assert "elongation" not in c.morphometrics
    assert "circularity" not in c.morphometrics
    assert c in apply_post_fuse_gate([c])


def test_apply_post_fuse_gate_keeps_candidate_with_only_one_shape_key():
    """Candidate with elongation but no circularity → circularity defaults to 1.0 → keep."""
    c = make_candidate(elongation=0.7, circularity=None)
    assert c in apply_post_fuse_gate([c])


# ===== T1.4 — Existing pre-fusion thresholds still enforced =====

def test_apply_post_fuse_gate_rejects_low_score():
    c = make_candidate(score=0.10, elongation=0.7, circularity=0.5)
    assert c not in apply_post_fuse_gate([c])


def test_apply_post_fuse_gate_rejects_tiny_area():
    c = make_candidate(area_m2=10.0, elongation=0.7, circularity=0.5)
    assert c not in apply_post_fuse_gate([c])


def test_apply_post_fuse_gate_rejects_shallow_depth():
    c = make_candidate(depth_m=0.1, elongation=0.7, circularity=0.5)
    assert c not in apply_post_fuse_gate([c])


def test_apply_post_fuse_gate_rejects_extreme_depth():
    c = make_candidate(depth_m=0.0, lrm_anomaly_m=200.0, elongation=0.7, circularity=0.5)
    assert c not in apply_post_fuse_gate([c])


# ===== T1.4 — Score boundary lock =====

@pytest.mark.parametrize("score,expected_kept", [
    (0.14999, False),
    (0.15000, False),  # AT threshold → rejected (<=)
    (0.15001, True),
])
def test_apply_post_fuse_gate_score_seam(score, expected_kept):
    c = make_candidate(score=score, elongation=0.7, circularity=0.5)
    assert (c in apply_post_fuse_gate([c])) is expected_kept


# ===== T1.5 — Empty input =====

def test_apply_post_fuse_gate_empty_input():
    assert apply_post_fuse_gate([]) == []


# ===== T1.6 — Multiple candidates, mixed accept/reject =====

def test_apply_post_fuse_gate_mixed_input_preserves_order():
    """Survivors come back in input order."""
    keep1 = make_candidate(elongation=0.7, circularity=0.5)
    drop = make_candidate(elongation=0.2, circularity=0.5)  # reject for elongation
    keep2 = make_candidate(elongation=0.6, circularity=0.4)
    result = apply_post_fuse_gate([keep1, drop, keep2])
    assert result == [keep1, keep2]


# ===== T2.6 — Allegheny Cemetery Cave regression at unit level =====

def test_allegheny_cemetery_cave_unit_metrics_pass_gate():
    """The validated 2026-04-02 cave detection's metrics survive the gate.

    These are illustrative defaults — 06-deploy-and-smoke.md T8 runs the same
    check against the live DB. If thresholds are tightened in the future and
    this fails, decide per-site whether to relax thresholds or accept that
    the cave needs its detection-mode rerun.
    """
    cave = make_candidate(
        score=0.65,
        area_m2=120.0,
        depth_m=2.1,
        elongation=0.55,    # somewhat elongated cave entrance
        circularity=0.42,   # not perfectly round
    )
    assert cave in apply_post_fuse_gate([cave])
