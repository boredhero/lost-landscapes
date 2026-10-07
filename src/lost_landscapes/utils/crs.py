"""Coordinate reference system helpers."""

import re
from pathlib import Path
from typing import Union

import rasterio

from lost_landscapes.utils.log_manager import log

_UTM_ZONE_RE = re.compile(r'UTM zone (\d+)([NS])')


def utm_zone_from_lon(lon: float) -> int:
    """Get UTM zone number from longitude."""
    zone = int((lon + 180) / 6) + 1
    log.debug("utm_zone_from_lon", lon=lon, zone=zone)
    return zone


def epsg_from_lonlat(lon: float, lat: float) -> int:
    """Get EPSG code for UTM zone at a given lon/lat.
    Returns EPSG for WGS84 UTM North (326xx) or South (327xx).
    """
    zone = utm_zone_from_lon(lon)
    hemisphere = "north" if lat >= 0 else "south"
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    log.debug("epsg_from_lonlat", lon=lon, lat=lat, zone=zone, hemisphere=hemisphere, epsg=epsg)
    return epsg


def resolve_epsg(crs_source: Union["rasterio.crs.CRS", str, Path, None]) -> int:
    """Extract horizontal EPSG from any CRS source — handles compound CRS, WKT-only, and file paths.
    Resolution order:
      1. Direct to_epsg() on the CRS object
      2. Extract horizontal sub-CRS from compound CRS (UTM + vertical datum)
      3. Regex parse 'UTM zone NN[NS]' from CRS WKT string
      4. Raise ValueError — never silently returns a wrong-zone fallback
    """
    from pyproj import CRS as PyprojCRS
    log.debug("resolve_epsg_start", input_type=type(crs_source).__name__, raw=str(crs_source)[:80] if crs_source else "None")
    # If given a Path, open the file and extract CRS
    if isinstance(crs_source, (str, Path)):
        path = Path(crs_source)
        if path.exists() and path.suffix in (".tif", ".tiff"):
            log.debug("crs_resolve_from_file", path=str(path))
            with rasterio.open(path) as src:
                crs_source = src.crs
            log.debug("crs_extracted_from_file", path=str(path), crs=str(crs_source)[:80])
        else:
            # Treat as WKT string
            try:
                crs_source = PyprojCRS(crs_source)
                log.debug("crs_parsed_from_wkt", wkt=str(crs_source)[:80])
            except Exception as e:
                log.error("crs_wkt_parse_failed", input=str(crs_source)[:120], error=str(e), exception=True)
                raise ValueError(f"Cannot parse CRS from string: {str(crs_source)[:120]}")
    if crs_source is None:
        raise ValueError("CRS is None — file has no CRS metadata embedded")
    # Ensure we have a pyproj CRS for compound handling
    if hasattr(crs_source, 'to_epsg'):
        epsg = crs_source.to_epsg()
        if epsg:
            log.debug("crs_resolved", method="direct_epsg", epsg=epsg, raw=str(crs_source)[:80])
            return epsg
    # Convert to pyproj CRS for compound CRS handling
    try:
        pcrs = PyprojCRS(crs_source)
    except Exception as e:
        log.error("crs_pyproj_parse_failed", raw=str(crs_source)[:120], error=str(e), exception=True)
        raise ValueError(f"Cannot parse CRS: {str(crs_source)[:120]}")
    # Try direct epsg on pyproj CRS (sometimes rasterio fails but pyproj succeeds)
    direct = pcrs.to_epsg()
    if direct:
        log.debug("crs_resolved", method="pyproj_direct", epsg=direct, raw=str(crs_source)[:80])
        return direct
    # Extract horizontal component from compound CRS
    if pcrs.is_compound and pcrs.sub_crs_list:
        log.debug("crs_compound_detected", sub_crs_count=len(pcrs.sub_crs_list), raw=str(crs_source)[:80])
        horiz = pcrs.sub_crs_list[0]
        h_epsg = horiz.to_epsg()
        if h_epsg:
            log.info("crs_resolved", method="compound_horizontal", epsg=h_epsg, compound=True, raw=str(crs_source)[:80])
            return h_epsg
    # Regex fallback: parse UTM zone from CRS WKT/name string
    # 269xx (NAD83 UTM North) is intentional here, NOT 326xx (WGS84 UTM North).
    # This path only triggers when pyproj can't parse the CRS, and the WKT string
    # we're regex-matching says "NAD83 / UTM zone ..." — because US LiDAR (USGS 3DEP,
    # PASDA, state sources) is NAD83. Using 326xx would be the wrong datum.
    # NAD83 vs WGS84 differ by ~1-2m in CONUS — within noise for 1m LiDAR — and
    # PROJ_NETWORK=OFF already forces the simple geocentric transform that treats
    # them as equivalent. Southern hemisphere uses 327xx (WGS84) because NAD83
    # is a North American datum with no southern zones.
    crs_str = str(crs_source)
    m = _UTM_ZONE_RE.search(crs_str)
    if m:
        zone = int(m.group(1))
        hemisphere = m.group(2)
        epsg = 26900 + zone if hemisphere == 'N' else 32700 + zone
        log.info("crs_resolved", method="regex_utm", epsg=epsg, zone=zone, hemisphere=hemisphere, raw=crs_str[:80])
        return epsg
    # All methods exhausted
    log.error("crs_resolution_failed", raw=crs_str[:200])
    raise ValueError(f"Cannot determine EPSG from CRS: {crs_str[:200]}")
