"""Detection pass abstract base class and core data types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import Point, Polygon

from lost_landscapes.utils.log_manager import log


class FeatureType(StrEnum):
    SINKHOLE = "sinkhole"
    CAVE_ENTRANCE = "cave_entrance"
    MINE_PORTAL = "mine_portal"
    DEPRESSION = "depression"
    COLLAPSE_PIT = "collapse_pit"
    SPRING = "spring"
    LAVA_TUBE = "lava_tube"
    SALT_DOME_COLLAPSE = "salt_dome_collapse"
    MOUND = "mound"
    PLATFORM = "platform"
    LINEAR_BANK = "linear_bank"
    LINEAR_DITCH = "linear_ditch"
    ENCLOSURE = "enclosure"
    REPEATED_PATTERN = "repeated_pattern"
    RIDGE = "ridge"
    HOLLOW = "hollow"
    SCARP = "scarp"
    UNKNOWN = "unknown"


@dataclass
class Candidate:
    """A single detection candidate from a pass."""

    geometry: Point
    outline: Polygon | None = None
    score: float = 0.0
    feature_type: FeatureType = FeatureType.UNKNOWN
    morphometrics: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PassInput:
    """All data available to a detection pass."""

    dem: NDArray[np.float32]
    transform: Any  # rasterio Affine
    crs: int
    derivatives: dict[str, NDArray[np.float32]]
    point_cloud: Any | None = None  # PDAL structured array
    tile_bbox: Polygon | None = None
    config: dict[str, Any] = field(default_factory=dict)


class DetectionPass(ABC):
    """Abstract base class for all detection passes.

    Each pass must implement:
      - name: unique identifier
      - version: semantic version
      - required_derivatives: list of derivative names needed
      - run(): execute detection on a PassInput
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this pass."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version of this pass implementation."""
        ...

    @property
    @abstractmethod
    def required_derivatives(self) -> list[str]:
        """List of derivative names this pass needs (e.g., ['slope', 'tpi'])."""
        ...

    @property
    def requires_point_cloud(self) -> bool:
        """Override to True if pass needs raw point cloud data."""
        return False

    @property
    def requires_gpu(self) -> bool:
        """Override to True if pass uses GPU acceleration."""
        return False

    @abstractmethod
    def run(self, input_data: PassInput) -> list[Candidate]:
        """Execute detection on the given input. Return list of candidates."""
        ...

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Validate and return pass-specific config. Override for custom validation."""
        log.debug("pass_validate_config", pass_name=self.name, config_keys=list(config.keys()))
        return config

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} v{self.version}>"
