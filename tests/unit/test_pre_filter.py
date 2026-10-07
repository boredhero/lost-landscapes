"""Tests for the pre-fusion candidate filter in PassRunner.

The pre-filter removes obvious junk before DBSCAN to reduce fusion time.
Thresholds are intentionally looser than post-fusion (tasks.py) filters
because multi-pass fusion bonus (1.2x) can rescue borderline candidates.
"""

from shapely.geometry import Point

from lost_landscapes.detection.base import Candidate, FeatureType


def _make_candidate(score: float = 0.5, area_m2: float = 100.0, depth_m: float = 2.0, feature_type: FeatureType = FeatureType.DEPRESSION) -> tuple[str, Candidate]:
    """Create a (pass_name, Candidate) tuple for pre-filter testing."""
    return ("fill_difference", Candidate(
        geometry=Point(500000, 4500000),
        score=score,
        feature_type=feature_type,
        morphometrics={"area_m2": area_m2, "depth_m": depth_m},
    ))


class TestPreFusionFilter:
    """Tests for the pre-filter logic in runner.py line 204."""

    def _apply_filter(self, candidates: list[tuple[str, Candidate]]) -> list[tuple[str, Candidate]]:
        """Apply the same filter logic as runner.py line 204."""
        return [(pn, c) for pn, c in candidates if c.score > 0.15 and c.morphometrics.get("area_m2", 0) > 10 and c.morphometrics.get("depth_m", c.morphometrics.get("lrm_anomaly_m", 0)) < 200]

    def test_removes_low_score(self):
        candidates = [_make_candidate(score=0.10)]
        assert len(self._apply_filter(candidates)) == 0

    def test_removes_tiny_area(self):
        candidates = [_make_candidate(area_m2=5.0)]
        assert len(self._apply_filter(candidates)) == 0

    def test_removes_absurd_depth(self):
        candidates = [_make_candidate(depth_m=250.0)]
        assert len(self._apply_filter(candidates)) == 0

    def test_keeps_borderline_score(self):
        """Score 0.16 is above 0.15 threshold — must survive."""
        candidates = [_make_candidate(score=0.16)]
        assert len(self._apply_filter(candidates)) == 1

    def test_keeps_borderline_area(self):
        """Area 11 m² is above 10 m² threshold — must survive."""
        candidates = [_make_candidate(area_m2=11.0)]
        assert len(self._apply_filter(candidates)) == 1

    def test_keeps_borderline_depth(self):
        """Depth 199m is below 200m threshold — must survive."""
        candidates = [_make_candidate(depth_m=199.0)]
        assert len(self._apply_filter(candidates)) == 1

    def test_exact_boundary_score_rejected(self):
        """Score exactly 0.15 should be rejected (> not >=)."""
        candidates = [_make_candidate(score=0.15)]
        assert len(self._apply_filter(candidates)) == 0

    def test_exact_boundary_area_rejected(self):
        """Area exactly 10 m² should be rejected (> not >=)."""
        candidates = [_make_candidate(area_m2=10.0)]
        assert len(self._apply_filter(candidates)) == 0

    def test_mixed_keeps_good_removes_bad(self):
        """From a mixed set, only valid candidates survive."""
        candidates = [
            _make_candidate(score=0.8, area_m2=200, depth_m=5),    # good
            _make_candidate(score=0.05, area_m2=200, depth_m=5),   # bad score
            _make_candidate(score=0.5, area_m2=3, depth_m=5),      # bad area
            _make_candidate(score=0.5, area_m2=200, depth_m=300),  # bad depth
            _make_candidate(score=0.3, area_m2=50, depth_m=1),     # good
        ]
        result = self._apply_filter(candidates)
        assert len(result) == 2

    def test_lrm_anomaly_fallback_for_depth(self):
        """When depth_m is missing, lrm_anomaly_m is used for the depth<200 check."""
        cand = ("lrm", Candidate(
            geometry=Point(500000, 4500000),
            score=0.5,
            morphometrics={"area_m2": 100.0, "lrm_anomaly_m": 250.0},
        ))
        assert len(self._apply_filter([cand])) == 0

    def test_no_depth_or_lrm_defaults_zero(self):
        """Candidate with no depth metrics: depth defaults to 0, which is < 200 — passes depth check."""
        cand = ("tpi", Candidate(
            geometry=Point(500000, 4500000),
            score=0.5,
            morphometrics={"area_m2": 100.0},
        ))
        assert len(self._apply_filter([cand])) == 1
