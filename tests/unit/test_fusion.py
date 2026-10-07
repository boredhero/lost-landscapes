"""Unit tests for multi-pass result fusion."""

import pytest
from shapely.geometry import Point

from lost_landscapes.detection.base import Candidate, FeatureType
from lost_landscapes.detection.fusion import ResultFuser


class TestResultFuser:
    def setup_method(self):
        self.fuser = ResultFuser(eps_m=15.0, min_confidence=0.2)

    def test_single_candidate_passes_through(self):
        candidates = [
            ("pass_a", Candidate(
                geometry=Point(-79.7, 39.8),
                score=0.8,
                feature_type=FeatureType.SINKHOLE,
            ))
        ]
        result = self.fuser.fuse(candidates)
        assert len(result) == 1
        assert result[0].score == pytest.approx(0.8)

    def test_nearby_candidates_merge(self):
        # Two candidates within 15m of each other should merge
        candidates = [
            ("pass_a", Candidate(
                geometry=Point(-79.70000, 39.80000),
                score=0.7,
                feature_type=FeatureType.SINKHOLE,
            )),
            ("pass_b", Candidate(
                geometry=Point(-79.70005, 39.80005),  # ~7m away
                score=0.6,
                feature_type=FeatureType.SINKHOLE,
            )),
        ]
        result = self.fuser.fuse(candidates)
        assert len(result) == 1

    def test_distant_candidates_stay_separate(self):
        candidates = [
            ("pass_a", Candidate(
                geometry=Point(-79.70000, 39.80000),
                score=0.7,
                feature_type=FeatureType.SINKHOLE,
            )),
            ("pass_b", Candidate(
                geometry=Point(-79.71000, 39.81000),  # ~1.4km away
                score=0.6,
                feature_type=FeatureType.CAVE_ENTRANCE,
            )),
        ]
        result = self.fuser.fuse(candidates)
        assert len(result) == 2

    def test_multi_pass_bonus(self):
        # 3+ passes should get confidence bonus
        fuser = ResultFuser(eps_m=15.0, multi_pass_bonus=1.5, min_confidence=0.0)
        candidates = [
            ("pass_a", Candidate(geometry=Point(-79.7, 39.8), score=0.5, feature_type=FeatureType.SINKHOLE)),
            ("pass_b", Candidate(geometry=Point(-79.7, 39.8), score=0.5, feature_type=FeatureType.SINKHOLE)),
            ("pass_c", Candidate(geometry=Point(-79.7, 39.8), score=0.5, feature_type=FeatureType.SINKHOLE)),
        ]
        result = fuser.fuse(candidates)
        assert len(result) == 1
        assert result[0].score > 0.5  # boosted

    def test_below_min_confidence_filtered(self):
        fuser = ResultFuser(min_confidence=0.5)
        candidates = [
            ("pass_a", Candidate(geometry=Point(-79.7, 39.8), score=0.2, feature_type=FeatureType.UNKNOWN)),
        ]
        result = fuser.fuse(candidates)
        assert len(result) == 0

    def test_empty_input(self):
        result = self.fuser.fuse([])
        assert len(result) == 0

    def test_weighted_scoring(self):
        fuser = ResultFuser(
            eps_m=15.0,
            weights={"pass_a": 2.0, "pass_b": 1.0},
            min_confidence=0.0,
        )
        candidates = [
            ("pass_a", Candidate(geometry=Point(-79.7, 39.8), score=0.8, feature_type=FeatureType.SINKHOLE)),
            ("pass_b", Candidate(geometry=Point(-79.7, 39.8), score=0.2, feature_type=FeatureType.DEPRESSION)),
        ]
        result = fuser.fuse(candidates)
        assert len(result) == 1
        # Weighted: (2.0*0.8 + 1.0*0.2) / (2.0+1.0) = 0.6
        assert result[0].score == pytest.approx(0.6, abs=0.05)
        # Higher-weighted pass should win type vote
        assert result[0].feature_type == FeatureType.SINKHOLE
