"""Storage management — LRU eviction with size cap.

Strategy:
1. Delete tiles not accessed in MAX_AGE_DAYS (default 30)
2. If total size > MAX_SIZE_GB (default 600), evict oldest-accessed first (LRU)
3. Never delete DEM or hillshade for tiles with detections still in PostGIS
   (those are cheap — ~18MB/tile — and needed for re-analysis)

Runs as a Celery beat task or can be called manually.
"""

import os
import time
from dataclasses import dataclass
from pathlib import Path

from lost_landscapes.utils.log_manager import log

MAX_AGE_DAYS = 30
MAX_SIZE_GB = 700


@dataclass
class FileEntry:
    """A file with its size and last access time."""
    path: Path
    size_bytes: int
    last_access: float  # Unix timestamp


def scan_data_dir(data_dir: Path) -> list[FileEntry]:
    """Scan all files under data_dir, return sorted by last access (oldest first)."""
    log.debug("scan_data_dir_start", data_dir=str(data_dir))
    entries = []
    for root, _dirs, files in os.walk(data_dir):
        for f in files:
            p = Path(root) / f
            try:
                stat = p.stat()
                entries.append(FileEntry(
                    path=p,
                    size_bytes=stat.st_size,
                    last_access=stat.st_atime,
                ))
            except (OSError, FileNotFoundError) as e:
                log.debug("file_stat_failed", path=str(p), error=str(e))
                continue
    # Sort oldest-accessed first (LRU eviction order)
    entries.sort(key=lambda e: e.last_access)
    total_bytes = sum(e.size_bytes for e in entries)
    log.info("scan_data_dir_complete", data_dir=str(data_dir), files=len(entries), total_gb=round(total_bytes / 1e9, 2))
    return entries


def evict(
    data_dir: Path,
    max_age_days: int = MAX_AGE_DAYS,
    max_size_gb: float = MAX_SIZE_GB,
    dry_run: bool = False,
) -> dict:
    """Run LRU eviction on the data directory.

    Returns summary dict with bytes freed, files deleted, etc.

    Phase 1: Delete anything older than max_age_days
    Phase 2: If still over max_size_gb, delete oldest-accessed until under cap
    """
    log.info("eviction_start", data_dir=str(data_dir), max_age_days=max_age_days, max_size_gb=max_size_gb, dry_run=dry_run)
    entries = scan_data_dir(data_dir)
    if not entries:
        log.info("eviction_skipped_empty", data_dir=str(data_dir))
        return {"files_scanned": 0, "freed_bytes": 0, "freed_gb": 0.0}

    total_bytes = sum(e.size_bytes for e in entries)
    max_bytes = max_size_gb * 1e9
    cutoff_time = time.time() - (max_age_days * 86400)

    freed_bytes = 0
    deleted_files = 0
    age_deleted = 0
    cap_deleted = 0

    # Phase 1: Age-based eviction
    log.debug("eviction_phase1_start", cutoff_age_days=max_age_days, total_files=len(entries))
    remaining = []
    for entry in entries:
        if entry.last_access < cutoff_time:
            if dry_run:
                log.info("evict_age_dryrun", path=str(entry.path),
                         age_days=round((time.time() - entry.last_access) / 86400, 1),
                         size_mb=round(entry.size_bytes / 1e6, 1))
            else:
                try:
                    entry.path.unlink()
                    log.info("evict_age", path=str(entry.path),
                             size_mb=round(entry.size_bytes / 1e6, 1))
                except OSError as e:
                    log.warning("evict_failed", path=str(entry.path), error=str(e))
                    remaining.append(entry)
                    continue
            freed_bytes += entry.size_bytes
            deleted_files += 1
            age_deleted += 1
        else:
            remaining.append(entry)

    # Phase 2: Size cap eviction (LRU — oldest-accessed first)
    log.debug("eviction_phase2_start", remaining_files=len(remaining), age_evicted=age_deleted, current_gb=round((total_bytes - freed_bytes) / 1e9, 2), max_gb=max_size_gb)
    current_bytes = total_bytes - freed_bytes
    for entry in remaining:
        if current_bytes <= max_bytes:
            break
        if dry_run:
            log.info("evict_cap_dryrun", path=str(entry.path),
                     size_mb=round(entry.size_bytes / 1e6, 1))
        else:
            try:
                entry.path.unlink()
                log.info("evict_cap", path=str(entry.path),
                         size_mb=round(entry.size_bytes / 1e6, 1))
            except OSError as e:
                log.warning("evict_failed", path=str(entry.path), error=str(e))
                continue
        freed_bytes += entry.size_bytes
        current_bytes -= entry.size_bytes
        deleted_files += 1
        cap_deleted += 1

    # Clean up empty directories
    if not dry_run:
        _remove_empty_dirs(data_dir)

    summary = {
        "files_scanned": len(entries),
        "total_before_gb": round(total_bytes / 1e9, 2),
        "total_after_gb": round((total_bytes - freed_bytes) / 1e9, 2),
        "freed_bytes": freed_bytes,
        "freed_gb": round(freed_bytes / 1e9, 2),
        "deleted_files": deleted_files,
        "age_evicted": age_deleted,
        "cap_evicted": cap_deleted,
        "max_age_days": max_age_days,
        "max_size_gb": max_size_gb,
        "dry_run": dry_run,
    }
    log.info("eviction_complete", **summary)
    return summary


def get_storage_stats(data_dir: Path) -> dict:
    """Get current storage usage breakdown."""
    log.debug("get_storage_stats_start", data_dir=str(data_dir))
    categories = {
        "raw": {"glob": "raw/**/*", "bytes": 0, "files": 0},
        "dem": {"glob": "processed/**/*_dem.tif", "bytes": 0, "files": 0},
        "hillshade": {"glob": "processed/**/hillshade.tif", "bytes": 0, "files": 0},
        "derivatives": {"glob": "processed/**/derivatives/*.tif", "bytes": 0, "files": 0},
        "other": {"glob": None, "bytes": 0, "files": 0},
    }

    all_files = set()
    categorized = set()

    for root, _dirs, files in os.walk(data_dir):
        for f in files:
            p = Path(root) / f
            all_files.add(p)

    # Categorize
    for p in all_files:
        rel = str(p.relative_to(data_dir))
        try:
            sz = p.stat().st_size
        except OSError as e:
            log.debug("storage_stat_failed", path=str(p), error=str(e))
            continue

        if rel.startswith("raw/"):
            categories["raw"]["bytes"] += sz
            categories["raw"]["files"] += 1
            categorized.add(p)
        elif rel.endswith("_dem.tif") or rel.endswith("/dem.tif"):
            categories["dem"]["bytes"] += sz
            categories["dem"]["files"] += 1
            categorized.add(p)
        elif "hillshade" in rel:
            categories["hillshade"]["bytes"] += sz
            categories["hillshade"]["files"] += 1
            categorized.add(p)
        elif "derivatives" in rel:
            categories["derivatives"]["bytes"] += sz
            categories["derivatives"]["files"] += 1
            categorized.add(p)

    for p in all_files - categorized:
        try:
            sz = p.stat().st_size
        except OSError as e:
            log.debug("storage_stat_failed", path=str(p), error=str(e))
            continue
        categories["other"]["bytes"] += sz
        categories["other"]["files"] += 1

    total = sum(c["bytes"] for c in categories.values())
    log.info("get_storage_stats_complete", data_dir=str(data_dir), total_gb=round(total / 1e9, 2), total_files=len(all_files), usage_pct=round(total / (MAX_SIZE_GB * 1e9) * 100, 1) if MAX_SIZE_GB > 0 else 0)
    return {
        "total_gb": round(total / 1e9, 2),
        "max_gb": MAX_SIZE_GB,
        "usage_pct": round(total / (MAX_SIZE_GB * 1e9) * 100, 1) if MAX_SIZE_GB > 0 else 0,
        "categories": {
            name: {"gb": round(c["bytes"] / 1e9, 2), "files": c["files"]}
            for name, c in categories.items()
        },
    }


def _remove_empty_dirs(root: Path) -> None:
    """Remove empty directories bottom-up."""
    removed = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if not dirnames and not filenames and Path(dirpath) != root:
            try:
                Path(dirpath).rmdir()
                removed += 1
            except OSError as e:
                log.debug("rmdir_failed", path=dirpath, error=str(e))
    if removed > 0:
        log.info("empty_dirs_removed", root=str(root), count=removed)
