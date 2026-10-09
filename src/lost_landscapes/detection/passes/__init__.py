"""Detection passes — import all to trigger registration."""

# Classical passes
from lost_landscapes.detection.passes.curvature import CurvaturePass
from lost_landscapes.detection.passes.fill_difference import FillDifferencePass
from lost_landscapes.detection.passes.local_relief_model import LocalReliefModelPass
from lost_landscapes.detection.passes.morphometric_filter import MorphometricFilterPass
from lost_landscapes.detection.passes.multi_return import MultiReturnPass
from lost_landscapes.detection.passes.point_density import PointDensityPass

# ML passes
from lost_landscapes.detection.passes.random_forest import RandomForestPass
from lost_landscapes.detection.passes.sky_view_factor import SkyViewFactorPass
from lost_landscapes.detection.passes.tpi import TPIPass
from lost_landscapes.detection.passes.unet_segmentation import UNetSegmentationPass
from lost_landscapes.detection.passes.yolo_detector import YOLODetectorPass

__all__ = [
    "FillDifferencePass",
    "LocalReliefModelPass",
    "CurvaturePass",
    "SkyViewFactorPass",
    "TPIPass",
    "PointDensityPass",
    "MultiReturnPass",
    "MorphometricFilterPass",
    "RandomForestPass",
    "UNetSegmentationPass",
    "YOLODetectorPass",
]

from lost_landscapes.detection.passes.discovery import (  # noqa: F401
    EnclosuresPass,
    GeologicalFormsPass,
    LinearFeaturesPass,
    RaisedFeaturesPass,
    RepeatedPatternsPass,
)
