"""Provider-independent context catalog and bounded raster request adapters.

Sources are operator-curated, never URLs supplied by a browser. New datasets use
catalog entries; new protocols implement request_for_tile without changing the UI.
"""

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lost_landscapes.config import settings

DEFAULT_CATALOG = Path(__file__).with_name("context-sources.json")


class Adapter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["arcgis-map", "arcgis-image", "xyz", "wms"]
    url: str
    layers: str = ""
    raster_ids: list[int] = Field(default_factory=list, max_length=16)
    styles: str = ""

    @model_validator(mode="after")
    def validate_adapter(self):
        url = urlsplit(self.url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Providers require a fixed HTTPS service URL without credentials or query")
        if self.kind in ("arcgis-map", "wms") and not self.layers:
            raise ValueError("Explicit layers required")
        if self.kind == "arcgis-image" and not self.raster_ids:
            raise ValueError("Historical imagery requires explicitly locked raster IDs")
        if self.kind == "xyz" and not all(f"{{{axis}}}" in self.url for axis in ("z", "x", "y")):
            raise ValueError("XYZ template must declare z/x/y")
        return self


class ContextSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    category: Literal["historical-map", "historical-aerial", "geology", "mining"]
    region: str
    country: str
    date_label: str
    date_kind: Literal["map-and-imprint", "flight", "publication", "map-and-revision", "inventory-check"]
    verified_at: str
    revision: str
    attribution: str
    source_url: str
    legend_url: str | None = None
    terms_url: str | None = None
    description: str
    limitations: str
    bounds: tuple[float, float, float, float]
    min_zoom: int = Field(0, ge=0, le=22)
    max_zoom: int = Field(18, ge=0, le=22)
    adapter: Adapter

    @model_validator(mode="after")
    def validate_source(self):
        w, s, e, n = self.bounds
        if not (-180 <= w < e <= 180 and -85.051129 <= s < n <= 85.051129):
            raise ValueError("Use WGS84 bounds; split antimeridian coverage into separate entries")
        if self.min_zoom > self.max_zoom:
            raise ValueError("Invalid zoom range")
        for value in (self.source_url, self.legend_url, self.terms_url):
            if value is not None and urlsplit(value).scheme != "https":
                raise ValueError("Source links must use HTTPS")
        return self

    def public(self):
        result = self.model_dump(exclude={"adapter"})
        result["provider"] = self.adapter.kind
        result["tile_url"] = f"/api/landscape/context/{self.id}/tiles/{{z}}/{{x}}/{{y}}.png?v={self.revision}"
        return result


@lru_cache(maxsize=1)
def source_catalog() -> dict[str, ContextSource]:
    path = settings.context_sources_path or DEFAULT_CATALOG
    raw = json.loads(Path(path).read_text())
    if raw.get("version") != 1:
        raise ValueError("Unsupported context catalog version")
    sources = [ContextSource.model_validate(item) for item in raw["sources"]]
    result = {s.id: s for s in sources}
    if len(result) != len(sources):
        raise ValueError("Context source IDs must be unique")
    return result


def geographic_tile_bounds(z, x, y):
    scale = 2**z
    return (x / scale * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / scale)))),
            (x + 1) / scale * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / scale)))))


def intersects(source, z, x, y):
    w, s, e, n = geographic_tile_bounds(z, x, y)
    a, b, c, d = source.bounds
    return e > a and w < c and n > b and s < d


def request_for_tile(source: ContextSource, z: int, x: int, y: int):
    """All adapters request EPSG:3857 rasters; native source reprojection is upstream.

    WMS deliberately uses 1.3.0 + EPSG:3857 (easting/northing axis order). Providers
    lacking that CRS require an explicit new adapter, not a silent CRS assumption.
    """
    adapter = source.adapter
    if adapter.kind == "xyz":
        return adapter.url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y)), {}
    world = 20037508.342789244
    width = world * 2 / 2**z
    bbox = ",".join(map(str, (-world + x * width, world - (y + 1) * width,
                              -world + (x + 1) * width, world - y * width)))
    if adapter.kind == "wms":
        return adapter.url, {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
                             "LAYERS": adapter.layers, "STYLES": adapter.styles, "CRS": "EPSG:3857",
                             "BBOX": bbox, "WIDTH": "256", "HEIGHT": "256", "FORMAT": "image/png", "TRANSPARENT": "TRUE"}
    params = {"f": "image", "bbox": bbox, "bboxSR": "3857", "imageSR": "3857",
              "size": "256,256", "format": "png32", "transparent": "true"}
    if adapter.kind == "arcgis-map":
        params["layers"] = f"show:{adapter.layers}"
        return adapter.url + "/export", params
    params["mosaicRule"] = json.dumps({"mosaicMethod": "esriMosaicLockRaster", "lockRasterIds": adapter.raster_ids, "mosaicOperation": "MT_FIRST"})
    return adapter.url + "/exportImage", params
