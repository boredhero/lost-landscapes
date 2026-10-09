"""Application configuration via environment variables."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = (
        "postgresql+asyncpg://localhost:5432/lost_landscapes"
    )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Data storage root (on remote machine)
    data_dir: Path = Path("data")

    # Optional operator-curated context catalog; the bundled registry is region-independent.
    context_sources_path: Path | None = None

    # Processing defaults
    dem_resolution_m: float = 1.0
    default_crs: int = 32617  # UTM zone 17N (covers western PA)

    # CPU budget for a shared four-core host; no server GPU required.
    terrain_workers: int = Field(2, ge=1, le=8)
    parallel_tiles: int = Field(1, ge=1, le=4)
    derivative_workers: int = Field(2, ge=1, le=8)
    detection_workers: int = Field(2, ge=1, le=8)
    download_workers: int = Field(2, ge=1, le=8)
    scan_tile_limit: int = Field(4, ge=1, le=50)
    enable_analysis: bool = False

    # Detection defaults
    min_confidence: float = 0.3
    fusion_dbscan_eps_m: float = 10.0
    multi_pass_bonus: float = 1.2

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Processing cache — set to false to skip .processed marker files (debug mode)
    enable_processing_cache: bool = True

    # OSM offline data (Geofabrik PBF + osmium)
    osm_cache_ttl_days: int = 30

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def ground_truth_dir(self) -> Path:
        return self.data_dir / "ground_truth"


settings = Settings()
