"""Tests for building and infrastructure postprocess filters.

These filters remove false positives by checking detections against OSM data
(buildings, roads, waterways, railways). The OSM data source is mocked — we
test the geometry filtering logic, not the data access.
"""

from unittest.mock import patch

import pytest
from shapely.geometry import Point, box

from lost_landscapes.detection.base import Candidate, FeatureType


def _make_candidate(lon: float, lat: float, feature_type: FeatureType = FeatureType.DEPRESSION) -> Candidate:
    return Candidate(geometry=Point(lon, lat), score=0.5, feature_type=feature_type, morphometrics={"area_m2": 100, "depth_m": 2})


# --- Building Filter ---

class TestBuildingFilter:
    """Tests for filter_candidates_by_buildings."""

    def test_candidate_inside_building_removed(self):
        from lost_landscapes.detection.postprocess.building_filter import (
            filter_candidates_by_buildings,
        )
        building = box(-79.95, 40.47, -79.94, 40.48)  # building polygon
        candidates = [_make_candidate(-79.945, 40.475)]  # inside building
        coords = [(-79.945, 40.475)]
        with patch("lost_landscapes.detection.postprocess.building_filter.fetch_building_polygons", return_value=[building]):
            result = filter_candidates_by_buildings(candidates, coords, -80, 40, -79, 41)
        assert len(result) == 0

    def test_candidate_outside_building_survives(self):
        from lost_landscapes.detection.postprocess.building_filter import (
            filter_candidates_by_buildings,
        )
        building = box(-79.95, 40.47, -79.94, 40.48)
        candidates = [_make_candidate(-79.90, 40.50)]  # outside building
        coords = [(-79.90, 40.50)]
        with patch("lost_landscapes.detection.postprocess.building_filter.fetch_building_polygons", return_value=[building]):
            result = filter_candidates_by_buildings(candidates, coords, -80, 40, -79, 41)
        assert len(result) == 1

    def test_no_buildings_returns_all_candidates(self):
        from lost_landscapes.detection.postprocess.building_filter import (
            filter_candidates_by_buildings,
        )
        candidates = [_make_candidate(-79.945, 40.475), _make_candidate(-79.90, 40.50)]
        coords = [(-79.945, 40.475), (-79.90, 40.50)]
        with patch("lost_landscapes.detection.postprocess.building_filter.fetch_building_polygons", return_value=[]):
            result = filter_candidates_by_buildings(candidates, coords, -80, 40, -79, 41)
        assert len(result) == 2

    def test_mixed_inside_and_outside(self):
        from lost_landscapes.detection.postprocess.building_filter import (
            filter_candidates_by_buildings,
        )
        building = box(-79.95, 40.47, -79.94, 40.48)
        inside = _make_candidate(-79.945, 40.475)
        outside = _make_candidate(-79.90, 40.50)
        coords = [(-79.945, 40.475), (-79.90, 40.50)]
        with patch("lost_landscapes.detection.postprocess.building_filter.fetch_building_polygons", return_value=[building]):
            result = filter_candidates_by_buildings([inside, outside], coords, -80, 40, -79, 41)
        assert len(result) == 1
        assert result[0][0].geometry.x == pytest.approx(-79.90)


class TestCemeteryExclusion:
    """Buildings inside cemeteries should NOT be used for filtering."""

    def test_cemetery_buildings_excluded_from_filter(self):
        from lost_landscapes.detection.postprocess.building_filter import fetch_building_polygons
        building_in_cemetery = box(-79.95, 40.47, -79.94, 40.48)
        cemetery = box(-79.96, 40.46, -79.93, 40.49)  # covers the building
        with patch("lost_landscapes.detection.postprocess.building_filter.get_building_polygons", return_value=[building_in_cemetery]), \
             patch("lost_landscapes.detection.postprocess.building_filter.get_cemetery_polygons", return_value=[cemetery]):
            result = fetch_building_polygons(-80, 40, -79, 41)
        # Building inside cemetery should be excluded
        assert len(result) == 0


# --- Infrastructure Filter ---

class TestInfrastructureFilter:
    """Tests for filter_candidates_by_infrastructure."""

    def _mock_infra(self, roads=None, water=None, railways=None, landuse=None):
        return {"roads": roads or [], "water": water or [], "railways": railways or [], "landuse": landuse or []}

    def test_candidate_on_road_removed(self):
        from shapely.geometry import LineString

        from lost_landscapes.detection.postprocess.infrastructure_filter import (
            filter_candidates_by_infrastructure,
        )
        road = LineString([(-80, 40.5), (-79, 40.5)]).buffer(0.001)
        infra = self._mock_infra(roads=[road])
        candidates = [_make_candidate(-79.5, 40.5)]  # right on the road
        coords = [(-79.5, 40.5)]
        with patch("lost_landscapes.detection.postprocess.infrastructure_filter.fetch_infrastructure_polygons", return_value=infra):
            result = filter_candidates_by_infrastructure(candidates, coords, -80, 40, -79, 41)
        assert len(result) == 0

    def test_candidate_away_from_road_survives(self):
        from shapely.geometry import LineString

        from lost_landscapes.detection.postprocess.infrastructure_filter import (
            filter_candidates_by_infrastructure,
        )
        road = LineString([(-80, 40.5), (-79, 40.5)]).buffer(0.001)
        infra = self._mock_infra(roads=[road])
        candidates = [_make_candidate(-79.5, 40.6)]  # far from road
        coords = [(-79.5, 40.6)]
        with patch("lost_landscapes.detection.postprocess.infrastructure_filter.fetch_infrastructure_polygons", return_value=infra):
            result = filter_candidates_by_infrastructure(candidates, coords, -80, 40, -79, 41)
        assert len(result) == 1

    def test_spring_exempt_from_water_filter(self):
        """Springs should survive water filtering — they're real geological features near water."""
        from lost_landscapes.detection.postprocess.infrastructure_filter import (
            filter_candidates_by_infrastructure,
        )
        water = box(-80, 40.4, -79, 40.6)  # covers everything
        infra = self._mock_infra(water=[water])
        spring = _make_candidate(-79.5, 40.5, feature_type=FeatureType.SPRING)
        depression = _make_candidate(-79.5, 40.5, feature_type=FeatureType.DEPRESSION)
        candidates = [spring, depression]
        coords = [(-79.5, 40.5), (-79.5, 40.5)]
        with patch("lost_landscapes.detection.postprocess.infrastructure_filter.fetch_infrastructure_polygons", return_value=infra):
            result = filter_candidates_by_infrastructure(candidates, coords, -80, 40, -79, 41)
        # Spring survives, depression doesn't
        assert len(result) == 1
        assert result[0][0].feature_type == FeatureType.SPRING

    def test_spring_still_removed_by_road(self):
        """Springs are only exempt from water — roads still remove them."""
        from lost_landscapes.detection.postprocess.infrastructure_filter import (
            filter_candidates_by_infrastructure,
        )
        road = box(-80, 40.4, -79, 40.6)
        infra = self._mock_infra(roads=[road])
        spring = _make_candidate(-79.5, 40.5, feature_type=FeatureType.SPRING)
        candidates = [spring]
        coords = [(-79.5, 40.5)]
        with patch("lost_landscapes.detection.postprocess.infrastructure_filter.fetch_infrastructure_polygons", return_value=infra):
            result = filter_candidates_by_infrastructure(candidates, coords, -80, 40, -79, 41)
        assert len(result) == 0

    def test_no_infrastructure_returns_all(self):
        from lost_landscapes.detection.postprocess.infrastructure_filter import (
            filter_candidates_by_infrastructure,
        )
        infra = self._mock_infra()
        candidates = [_make_candidate(-79.5, 40.5)]
        coords = [(-79.5, 40.5)]
        with patch("lost_landscapes.detection.postprocess.infrastructure_filter.fetch_infrastructure_polygons", return_value=infra):
            result = filter_candidates_by_infrastructure(candidates, coords, -80, 40, -79, 41)
        assert len(result) == 1

    def test_railway_removes_candidate(self):
        from lost_landscapes.detection.postprocess.infrastructure_filter import (
            filter_candidates_by_infrastructure,
        )
        rail = box(-80, 40.49, -79, 40.51)
        infra = self._mock_infra(railways=[rail])
        candidates = [_make_candidate(-79.5, 40.5)]
        coords = [(-79.5, 40.5)]
        with patch("lost_landscapes.detection.postprocess.infrastructure_filter.fetch_infrastructure_polygons", return_value=infra):
            result = filter_candidates_by_infrastructure(candidates, coords, -80, 40, -79, 41)
        assert len(result) == 0
