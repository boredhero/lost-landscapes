"""Tests for detection pass registry — pure Python, no GDAL needed."""

import pytest

from lost_landscapes.detection.registry import PassRegistry


class TestPassRegistry:
    def test_all_11_passes_registered(self):
        passes = PassRegistry.list_passes()
        expected = [
            "fill_difference", "local_relief_model", "curvature",
            "sky_view_factor", "tpi", "point_density", "multi_return",
            "morphometric_filter", "random_forest", "unet_segmentation",
            "yolo_detector",
        ]
        for name in expected:
            assert name in passes, f"Pass {name!r} not registered"
        assert len(passes) == 11

    def test_get_pass_chain(self):
        chain = PassRegistry.get_pass_chain(["fill_difference", "tpi"])
        assert len(chain) == 2
        assert chain[0].name == "fill_difference"
        assert chain[1].name == "tpi"

    def test_unknown_pass_raises(self):
        with pytest.raises(KeyError, match="nonexistent"):
            PassRegistry.get("nonexistent")
