"""Synthetic morphology correctness, not evidence of real-world detection accuracy."""

import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import Point

from lost_landscapes.detection.base import FeatureType, PassInput
from lost_landscapes.detection.geometry_support import PASSES, prepare
from lost_landscapes.detection.passes.discovery import (
    EnclosuresPass,
    GeologicalFormsPass,
    LinearFeaturesPass,
    RaisedFeaturesPass,
    RepeatedPatternsPass,
)
from lost_landscapes.detection.postprocess.pipeline_glue import run_post_fuse_chain
from lost_landscapes.detection.runner import PassRunner


def surface(dx=1, dy=1):
    y, x = np.mgrid[0:200:dy, 0:200:dx]
    return x, y, from_origin(500000, 4400200, dx, dy)


def run(pass_class, dem, transform, config=None):
    derivatives = prepare(dem.astype('float32'), transform, 32617)
    return pass_class().run(PassInput(dem=dem, transform=transform, crs=32617, derivatives=derivatives, config=config or {}))


@pytest.mark.parametrize('dx,dy', [(1, 1), (2, 2), (1, 2)])
def test_mound_on_sloping_ground_metric_grid(dx, dy):
    x, y, t = surface(dx, dy)
    dem = 100 + .05 * x + 3 * np.exp(-((x-100)**2+(y-100)**2)/50)
    candidates = run(RaisedFeaturesPass, dem, t)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.feature_type == FeatureType.MOUND
    assert 50 < c.morphometrics['area_m2'] < 250
    assert c.morphometrics['height_residual_m'] > 1.5
    assert c.outline.is_valid and c.outline.covers(c.geometry)
    assert c.metadata['experimental'] and 'probability' in c.metadata['score_kind']


def test_flat_platform():
    x, y, t = surface()
    dem = 100 + 3 * ((abs(x-100) < 7) & (abs(y-100) < 7))
    assert any(c.feature_type == FeatureType.PLATFORM for c in run(RaisedFeaturesPass, dem, t))


@pytest.mark.parametrize('sign,kind', [(1, FeatureType.LINEAR_BANK), (-1, FeatureType.LINEAR_DITCH)])
def test_linear_banks_and_ditches(sign, kind):
    x, y, t = surface()
    dem = 100 + sign * 2 * ((abs(x-100) < 3) & (abs(y-100) < 35))
    candidates = run(LinearFeaturesPass, dem, t)
    matching = [c for c in candidates if c.feature_type == kind]
    assert matching and matching[0].morphometrics['length_m'] >= 60
    assert matching[0].morphometrics['width_m'] <= 8


def test_closed_enclosure_but_not_open_or_nodata_ring():
    x, y, t = surface()
    distance = np.maximum(abs(x-100), abs(y-100))
    dem = 100 + 2 * ((distance >= 18) & (distance <= 21))
    assert any(c.feature_type == FeatureType.ENCLOSURE for c in run(EnclosuresPass, dem, t))
    opened = dem.copy().astype(float)
    opened[abs(x-100) < 5] = 100
    assert run(EnclosuresPass, opened, t) == []
    missing = dem.astype(float)
    missing[(abs(x-100) < 2) & (abs(y-100) < 2)] = np.nan
    assert run(EnclosuresPass, missing, t) == []


def test_regular_repeated_mounds_and_irregular_negative():
    x, y, t = surface()
    def scene(centers):
        return 100 + sum(3 * np.exp(-((x-cx)**2+(y-cy)**2)/18) for cx, cy in centers)
    result = run(RepeatedPatternsPass, scene([(65,100),(100,100),(135,100)]), t)
    assert len(result) == 1
    assert result[0].morphometrics['member_count'] == 3
    assert result[0].morphometrics['spacing_cv'] < .05
    assert run(RepeatedPatternsPass, scene([(60,100),(80,100),(140,100)]), t) == []


@pytest.mark.parametrize('sign,kind', [(1, FeatureType.RIDGE), (-1, FeatureType.HOLLOW)])
def test_broad_geological_forms(sign, kind):
    x, y, t = surface()
    dem = 100 + sign * 5 * np.exp(-((x-100)**2)/90) * (abs(y-100)<50)
    assert any(c.feature_type == kind for c in run(GeologicalFormsPass, dem, t))


def test_scarp():
    x, y, t = surface()
    dem = 100 + 8 * np.clip((x-95)/5, 0, 1) * np.clip((145-x)/15, 0, 1) * np.clip((145-y)/15, 0, 1) * np.clip((y-55)/15, 0, 1)
    assert any(c.feature_type == FeatureType.SCARP for c in run(GeologicalFormsPass, dem, t))


@pytest.mark.parametrize('pass_class', [RaisedFeaturesPass, LinearFeaturesPass, EnclosuresPass, RepeatedPatternsPass, GeologicalFormsPass])
def test_flat_plane_and_missing_ground_do_not_create_features(pass_class):
    x, y, t = surface()
    dem = 100 + .02*x + .01*y
    dem[70:80, 70:80] = np.nan
    assert run(pass_class, dem, t) == []


def test_clipped_mound_rejected():
    x, y, t = surface()
    dem = 100 + 4*np.exp(-((x-8)**2+(y-100)**2)/80)
    assert run(RaisedFeaturesPass, dem, t) == []


def test_bounds_units_parameters_and_missing_derivatives():
    dem = np.zeros((30,30), dtype='float32')
    with pytest.raises(ValueError, match='metre'):
        prepare(dem, from_origin(0,1,1,1), 4326)
    with pytest.raises(ValueError, match='metre'):
        prepare(dem, from_origin(0,1,1,1), 2272)
    with pytest.raises(ValueError, match='4 million'):
        prepare(np.broadcast_to(0., (2001,2001)), from_origin(0,1,1,1), 32617)
    with pytest.raises(ValueError, match='Invalid'):
        run(RaisedFeaturesPass, dem, from_origin(0,1,1,1), {'threshold_m': -1})
    with pytest.raises(ValueError, match='Missing'):
        RaisedFeaturesPass().run(PassInput(dem, from_origin(0,1,1,1), 32617, {}))


def test_runner_preserves_families_evidence_and_postfilters():
    x, y, t = surface()
    dem = 100 + 2*((abs(x-100)<3)&(abs(y-100)<35))
    candidates = PassRunner(['linear_features']).run_on_array(dem, t, 32617)
    assert any(c.feature_type == FeatureType.LINEAR_BANK for c in candidates)
    def must_not_filter(*args):
        pytest.fail('Depression-specific infrastructure filter consumed discovery geometry')
    out = run_post_fuse_chain(candidates, [(0,0)]*len(candidates), (0,0,1,1), infra_filter_func=must_not_filter)
    assert len(out) == len(candidates)
    assert all(c.metadata['algorithm_version'] == '0.1.0' for c,_,_ in out)
    assert all(c.metadata['crs'] == 'EPSG:32617' for c,_,_ in out)


def test_all_pass_config_and_masked_dem_roundtrip(tmp_path):
    import rasterio

    from lost_landscapes.pass_configs import pass_config_path
    x,y,t = surface()
    dem = 100 + 3*np.exp(-((x-100)**2+(y-100)**2)/50)
    dem[30:35, 30:35] = -9999
    path = tmp_path/'dem.tif'
    with rasterio.open(path, 'w', driver='GTiff', height=200, width=200, count=1, dtype='float32', crs=32617, transform=t, nodata=-9999) as dst:
        dst.write(dem.astype('float32'),1)
    runner = PassRunner.from_toml(pass_config_path('landscape_discovery'))
    assert {p.name for p in runner.passes} == PASSES
    candidates = runner.run_on_dem(path)
    assert candidates
    assert any(c.feature_type == FeatureType.MOUND for c in candidates)
    assert all(c.geometry.distance(Point(500032,4400168))>20 for c in candidates)
