"""CLI entry point for lost-landscapes."""

import asyncio
import time

import click

from lost_landscapes.utils.log_manager import log, set_request_id


@click.group()
def main():
    """Lost Landscapes — LiDAR terrain anomaly detection platform."""
    set_request_id("cli")


@main.command()
@click.option("--lat", required=True, type=float, help="Center latitude")
@click.option("--lon", required=True, type=float, help="Center longitude")
@click.option("--radius", default=5.0, type=float, help="Radius in km (default 5)")
def discover(lat: float, lon: float, radius: float):
    """Discover available LiDAR tiles for a location."""
    from shapely.geometry import box

    from lost_landscapes.ingest.manager import discover_tiles_for_bbox
    log.info("cli_discover_start", lat=lat, lon=lon, radius_km=radius)
    t0 = time.perf_counter()
    r = radius / 111.32
    bbox = box(lon - r, lat - r, lon + r, lat + r)
    try:
        tiles, source = asyncio.run(discover_tiles_for_bbox(bbox, lat, lon))
        elapsed = round(time.perf_counter() - t0, 2)
        log.info("cli_discover_complete", tiles_found=len(tiles), source=source, elapsed_s=elapsed)
        click.echo(f"Found {len(tiles)} tiles via {source}")
        for tile in tiles[:10]:
            click.echo(f"  {tile.source_id}: {tile.format} ({tile.file_size_bytes or '?'} bytes)")
        if len(tiles) > 10:
            click.echo(f"  ... and {len(tiles) - 10} more")
    except Exception as e:
        log.error("cli_discover_failed", error=str(e), lat=lat, lon=lon, exception=True)
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


@main.command()
def seed():
    """Seed the database with known validation sites."""
    from scripts.seed_validation_sites import seed as do_seed
    log.info("cli_seed_start")
    t0 = time.perf_counter()
    try:
        asyncio.run(do_seed())
        elapsed = round(time.perf_counter() - t0, 2)
        log.info("cli_seed_complete", elapsed_s=elapsed)
    except Exception as e:
        log.error("cli_seed_failed", error=str(e), exception=True)
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


if __name__ == "__main__":
    main()
