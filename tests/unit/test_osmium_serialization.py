"""Tests for the osmium-extract serialization lock in osm_data.py.

Locks the invariant that `osmium extract` calls cannot run concurrently —
removing the `with _OSMIUM_EXTRACT_LOCK:` wrapper would fail the
serialization test below.
"""

import threading
import time

from lost_landscapes.utils import osm_data


def test_osmium_extract_lock_exists_and_is_a_semaphore():
    """The module-level lock exists and is a Semaphore — caught early if removed by refactor."""
    assert hasattr(osm_data, "_OSMIUM_EXTRACT_LOCK")
    lock = osm_data._OSMIUM_EXTRACT_LOCK
    # threading.Semaphore exposes acquire/release; verify it's the right shape
    assert hasattr(lock, "acquire")
    assert hasattr(lock, "release")


def test_osmium_extract_lock_serializes_concurrent_calls(tmp_path, monkeypatch):
    """N concurrent threads calling _extract_geojson invoke osmium extract sequentially.

    Detection: instrument subprocess.run via monkeypatch to record start/end timestamps.
    If serialization works, no two windows overlap. If the lock were removed, we'd
    see N concurrent windows (overlapping start/end intervals).
    """
    # Ensure PBF + config paths exist so _extract_geojson reaches the subprocess.run call
    monkeypatch.setattr(osm_data, "PBF_PATH", tmp_path / "fake.pbf")
    (tmp_path / "fake.pbf").write_bytes(b"")  # exists, contents irrelevant (subprocess is mocked)
    monkeypatch.setattr(osm_data, "OSMIUM_CONFIGS_DIR", tmp_path)
    (tmp_path / "roads.json").write_text("{}")  # config exists
    # Isolate the clip cache so each call re-runs extract (mocked extract never writes a clip file)
    monkeypatch.setattr(osm_data, "CLIP_CACHE_DIR", tmp_path / "clips")

    # Each fake subprocess.run sleeps 50ms to make windows measurable
    windows: list[tuple[float, float, str]] = []
    windows_lock = threading.Lock()

    def fake_run(cmd, *args, **kwargs):
        cmd_kind = cmd[1] if len(cmd) > 1 else "?"
        start = time.perf_counter()
        time.sleep(0.05)
        end = time.perf_counter()
        with windows_lock:
            windows.append((start, end, cmd_kind))
        # Mimic a successful subprocess result with empty geojson
        class _R:
            returncode = 0
            stderr = ""
            stdout = ""
        # Make the export step write a tiny empty geojson so the read path works
        if cmd_kind == "export":
            out_path = cmd[cmd.index("-o") + 1]
            from pathlib import Path
            Path(out_path).write_text('{"type":"FeatureCollection","features":[]}')
        return _R()

    monkeypatch.setattr(osm_data.subprocess, "run", fake_run)

    def call_extract():
        osm_data._extract_geojson(-79.96, 40.46, -79.94, 40.48, "roads")

    threads = [threading.Thread(target=call_extract) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    extract_windows = [(s, e) for s, e, kind in windows if kind == "extract"]
    assert len(extract_windows) == 5, f"Expected 5 extract calls, got {len(extract_windows)}"

    # Sort by start time and verify no overlap between consecutive windows
    extract_windows.sort()
    for (s1, e1), (s2, e2) in zip(extract_windows, extract_windows[1:]):
        assert s2 >= e1 - 0.005, (
            f"Extract windows overlap: ({s1:.3f},{e1:.3f}) and ({s2:.3f},{e2:.3f}) "
            f"— serialization broken (lock removed?)"
        )


def test_osmium_export_is_NOT_serialized_intentionally(tmp_path, monkeypatch):
    """Export operates on tiny per-tile clip files and has no need to serialize.

    Verify export calls CAN run concurrently — this is by design (the lock is
    extract-only). Catches a future over-broad refactor that would tank
    throughput by serializing export too.
    """
    monkeypatch.setattr(osm_data, "PBF_PATH", tmp_path / "fake.pbf")
    (tmp_path / "fake.pbf").write_bytes(b"")
    monkeypatch.setattr(osm_data, "OSMIUM_CONFIGS_DIR", tmp_path)
    (tmp_path / "roads.json").write_text("{}")
    monkeypatch.setattr(osm_data, "CLIP_CACHE_DIR", tmp_path / "clips")

    overlap_observed = threading.Event()
    in_export = threading.Lock()
    active_exports = [0]

    def fake_run(cmd, *args, **kwargs):
        cmd_kind = cmd[1] if len(cmd) > 1 else "?"
        if cmd_kind == "export":
            with in_export:
                active_exports[0] += 1
                if active_exports[0] >= 2:
                    overlap_observed.set()
            time.sleep(0.05)
            with in_export:
                active_exports[0] -= 1
            out_path = cmd[cmd.index("-o") + 1]
            from pathlib import Path
            Path(out_path).write_text('{"type":"FeatureCollection","features":[]}')
        class _R:
            returncode = 0
            stderr = ""
            stdout = ""
        return _R()

    monkeypatch.setattr(osm_data.subprocess, "run", fake_run)

    def call_extract():
        osm_data._extract_geojson(-79.96, 40.46, -79.94, 40.48, "roads")

    threads = [threading.Thread(target=call_extract) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert overlap_observed.is_set(), (
        "Export should be parallelizable (no lock); did someone wrap export "
        "with _OSMIUM_EXTRACT_LOCK by mistake?"
    )


def test_celery_task_time_limit_is_at_least_2hrs():
    """Lock the time-limit ceiling so future tightening is intentional.

    A 50-tile scan with serialized osmium needs ~30-100 min depending on
    cache hits. 2 hr is the minimum safe ceiling.
    """
    from lost_landscapes.workers.celery_app import app
    assert app.conf.task_time_limit >= 7200, (
        f"task_time_limit={app.conf.task_time_limit}; must be >= 7200s (2 hr) "
        "to fit a 50-tile scan with serialized osmium extracts."
    )
    # Soft limit must be strictly less than hard limit so the worker can do cleanup
    assert app.conf.task_soft_time_limit < app.conf.task_time_limit
