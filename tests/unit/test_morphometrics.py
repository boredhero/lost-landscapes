"""Tests for morphometric computations — pure Python, no GDAL needed."""

import numpy as np
import pytest

from lost_landscapes.detection.postprocess.morphometrics import (
    compute_area,
    compute_circularity,
    compute_depth,
    compute_elongation,
    compute_k_parameter,
    compute_volume,
)


class TestDepth:
    def test_simple_pit(self):
        dem = np.array([[10, 10, 10], [10, 5, 10], [10, 10, 10]], dtype=np.float32)
        mask = np.ones((3, 3), dtype=bool)
        assert compute_depth(dem, mask) == pytest.approx(5.0)

    def test_empty_mask(self):
        dem = np.ones((3, 3), dtype=np.float32)
        assert compute_depth(dem, np.zeros((3, 3), dtype=bool)) == 0.0


class TestArea:
    def test_computation(self):
        mask = np.zeros((10, 10), dtype=bool)
        mask[3:7, 3:7] = True
        assert compute_area(mask, resolution_m=2.0) == pytest.approx(64.0)


class TestCircularity:
    def test_perfect_circle(self):
        size = 100
        y, x = np.mgrid[0:size, 0:size]
        mask = (x - 50) ** 2 + (y - 50) ** 2 < 30**2
        area = float(np.sum(mask))
        perimeter = float(np.sum(mask & ~np.roll(mask, 1, axis=0)))
        assert compute_circularity(area, perimeter) > 0.5

    def test_zero_perimeter(self):
        assert compute_circularity(100.0, 0.0) == 0.0


class TestKParameter:
    def test_cylinder(self):
        area, depth = 100.0, 5.0
        assert compute_k_parameter(area, depth, area * depth) == pytest.approx(1.0)

    def test_cone(self):
        area, depth = 100.0, 5.0
        assert compute_k_parameter(area, depth, area * depth / 3.0) == pytest.approx(3.0)


class TestVolume:
    def test_computation(self):
        dem = np.array([[10, 10, 10], [10, 7, 10], [10, 10, 10]], dtype=np.float32)
        mask = np.ones((3, 3), dtype=bool)
        assert compute_volume(dem, mask, resolution_m=1.0) == pytest.approx(3.0)


class TestElongation:
    def test_circular(self):
        size = 50
        y, x = np.mgrid[0:size, 0:size]
        mask = (x - 25) ** 2 + (y - 25) ** 2 < 10**2
        assert compute_elongation(mask) > 0.8

    def test_elongated(self):
        mask = np.zeros((50, 200), dtype=bool)
        mask[20:30, 10:190] = True
        assert compute_elongation(mask) < 0.4
