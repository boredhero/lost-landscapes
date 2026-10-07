"""Tests for run_post_fuse_chain — locks the cap-after-filters ordering.

This is the headline cap-reorder bug fix from sub-plan 02. Before the fix,
the top-200 cap ran BEFORE the building/infra filters. With the
DBSCAN multi-pass-bonus pumping linear road-edge depressions to high scores
(they hit fill_difference + LRM + TPI + curvature simultaneously), the cap
selected mostly road FPs, which the infra filter then chewed through —
leaving very few real candidates to be stored. Now the cap runs LAST, so
it evaluates over the genuinely-survived set.
"""

import pytest

from lost_landscapes.detection.postprocess.pipeline_glue import run_post_fuse_chain
from tests.conftest import make_candidate


def _identity_filter(cands, coords, *_args, **_kwargs):
    """No-op filter — passes everything through as (c, lon, lat) tuples."""
    return [(c, lon, lat) for c, (lon, lat) in zip(cands, coords)]


def _on_road_rejector(cands, coords, *_args, **_kwargs):
    """Test stub: rejects candidates whose `on_road` attribute is True.

    Mirrors the production infra filter signature. We tag fake-FP candidates
    with `on_road=True` via the test factory's `metadata_extra`.
    """
    out = []
    for c, (lon, lat) in zip(cands, coords):
        if not c.metadata.get("on_road", False):
            out.append((c, lon, lat))
    return out


def _make_paired_input(n_fps: int, n_reals: int):
    """FPs have HIGH scores + linear shape; reals have LOWER scores + round shape.

    Per the bug: with the cap running BEFORE infra, FPs (high score, on_road=True)
    crowd the cap and reals (low score) get culled. After the fix, infra rejects
    FPs first, so all reals survive the cap.
    """
    # FPs: round-enough to pass shape gate but flagged on_road for infra rejection.
    # We deliberately set elongation/circularity ABOVE the gate's thresholds so the
    # gate keeps them — letting us test that infra filter (not gate) is what kills them.
    fps = [
        make_candidate(
            score=0.9 - i * 0.0001,
            elongation=0.5,
            circularity=0.4,
            metadata_extra={"on_road": True, "label": f"fp_{i}"},
        )
        for i in range(n_fps)
    ]
    reals = [
        make_candidate(
            score=0.4 + i * 0.0001,
            elongation=0.7,
            circularity=0.5,
            metadata_extra={"on_road": False, "label": f"real_{i}"},
        )
        for i in range(n_reals)
    ]
    candidates = fps + reals
    coords = [(0.0, 0.0)] * len(candidates)
    return candidates, coords, fps, reals


# ===== T2.3 — The headline cap-reorder bug =====

def test_cap_runs_after_infrastructure_filter():
    """200 high-score road-FPs + 50 round-real with lower scores: ALL 50 reals survive."""
    candidates, coords, fps, reals = _make_paired_input(n_fps=200, n_reals=50)
    bbox = (-1.0, -1.0, 1.0, 1.0)
    final = run_post_fuse_chain(
        candidates, coords, bbox,
        cap=200,
        buildings_filter_func=None,
        infra_filter_func=_on_road_rejector,
    )
    final_labels = {item[0].metadata["label"] for item in final}
    expected_real_labels = {r.metadata["label"] for r in reals}
    assert expected_real_labels.issubset(final_labels), (
        f"Real candidates were culled. Missing: {expected_real_labels - final_labels}"
    )
    # All 200 FPs should be rejected by the infra filter, leaving only the 50 reals.
    assert len(final) == 50
    # And no FP should appear in the final list.
    for item in final:
        assert item[0].metadata.get("on_road") is False


# ===== T2.4 — Cap-size edge cases (off-by-one paranoia) =====

@pytest.mark.parametrize("n_input,expected_size", [
    (0, 0),
    (1, 1),
    (199, 199),
    (200, 200),
    (201, 200),
    (1000, 200),
])
def test_post_fuse_chain_cap_size(n_input, expected_size):
    """Cap is exactly 200 across edge sizes; no off-by-one bug."""
    candidates = [
        make_candidate(score=1.0 - i * 0.0001, elongation=0.7, circularity=0.5)
        for i in range(n_input)
    ]
    coords = [(0.0, 0.0)] * n_input
    bbox = (-1.0, -1.0, 1.0, 1.0)
    final = run_post_fuse_chain(
        candidates, coords, bbox,
        cap=200,
        buildings_filter_func=_identity_filter,
        infra_filter_func=_identity_filter,
    )
    assert len(final) == expected_size


# ===== T2.5 — Sort order: highest score first =====

def test_post_fuse_chain_returns_highest_score_first():
    """Cap takes top N by score, so survivors are sorted by score DESC."""
    candidates = [
        make_candidate(score=0.5 + i * 0.05, elongation=0.7, circularity=0.5)
        for i in range(5)
    ]
    coords = [(0.0, 0.0)] * 5
    bbox = (-1.0, -1.0, 1.0, 1.0)
    final = run_post_fuse_chain(
        candidates, coords, bbox,
        cap=200,
        buildings_filter_func=_identity_filter,
        infra_filter_func=_identity_filter,
    )
    scores = [item[0].score for item in final]
    assert scores == sorted(scores, reverse=True)


# ===== T2.6 — Empty input short-circuits =====

def test_post_fuse_chain_empty_input_returns_empty():
    final = run_post_fuse_chain(
        [], [], (-1.0, -1.0, 1.0, 1.0),
        cap=200,
        buildings_filter_func=_identity_filter,
        infra_filter_func=_identity_filter,
    )
    assert final == []


# ===== T2.7 — All-rejected by gate short-circuits cleanly =====

def test_post_fuse_chain_all_gate_rejected_returns_empty():
    """If the shape gate eliminates everything, infra filter is never called."""
    # All candidates have elongation=0.1 (very linear), reject at gate
    candidates = [
        make_candidate(score=0.5, elongation=0.1, circularity=0.5)
        for _ in range(10)
    ]
    coords = [(0.0, 0.0)] * 10
    final = run_post_fuse_chain(
        candidates, coords, (-1.0, -1.0, 1.0, 1.0),
        cap=200,
        buildings_filter_func=_identity_filter,
        infra_filter_func=_identity_filter,
    )
    assert final == []


# ===== T2.8 — Filter order CAN be observed by tracking calls =====

def test_post_fuse_chain_invokes_buildings_then_infra_then_cap():
    """Verifies call order: buildings BEFORE infra, both BEFORE the cap."""
    call_order: list[str] = []

    def _buildings_recorder(cands, coords, *_a, **_kw):
        call_order.append("buildings")
        return [(c, lon, lat) for c, (lon, lat) in zip(cands, coords)]

    def _infra_recorder(cands, coords, *_a, **_kw):
        call_order.append("infra")
        return [(c, lon, lat) for c, (lon, lat) in zip(cands, coords)]

    candidates = [make_candidate(score=0.5, elongation=0.7, circularity=0.5) for _ in range(3)]
    coords = [(0.0, 0.0)] * 3
    run_post_fuse_chain(
        candidates, coords, (-1.0, -1.0, 1.0, 1.0),
        cap=2,  # cap below input size to verify cap runs LAST
        buildings_filter_func=_buildings_recorder,
        infra_filter_func=_infra_recorder,
    )
    assert call_order == ["buildings", "infra"]
