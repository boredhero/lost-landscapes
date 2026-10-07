"""Performance instrumentation — timing, memory, and pipeline profiling.

Provides:
  - StageTimer: context manager for timing individual stages
  - PipelineProfiler: collects all stage timings into a structured report
  - @timed decorator for functions
  - Memory snapshots via /proc/self/status (Linux) or psutil fallback
"""

import functools
import os
import threading
import time
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from lost_landscapes.utils.log_manager import log


@dataclass
class StageResult:
    """Timing result for a single pipeline stage."""

    name: str
    elapsed_s: float
    parent: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_ms(self) -> float:
        return self.elapsed_s * 1000


def get_memory_mb() -> float:
    """Get current RSS memory usage in MB. Fast, no imports needed on Linux."""
    try:
        # Fast path: read /proc directly (Linux only, no external deps)
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024  # kB → MB
    except (FileNotFoundError, ValueError, IndexError):
        pass
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0


def get_cpu_count() -> int:
    """Get available CPU count, respecting cgroup limits (Docker)."""
    try:
        # cgroup v2 (Docker)
        with open("/sys/fs/cgroup/cpu.max") as f:
            parts = f.read().strip().split()
            if parts[0] != "max":
                quota = int(parts[0])
                period = int(parts[1])
                return max(1, quota // period)
    except (FileNotFoundError, ValueError):
        pass
    try:
        # cgroup v1
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as f:
            quota = int(f.read().strip())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as f:
            period = int(f.read().strip())
        if quota > 0:
            return max(1, quota // period)
    except (FileNotFoundError, ValueError):
        pass
    return os.cpu_count() or 1


def get_gpu_info() -> dict[str, Any]:
    """Detect GPU availability (ROCm/CUDA) without importing torch."""
    info: dict[str, Any] = {"available": False}
    try:
        import torch
        if torch.cuda.is_available():
            info["available"] = True
            info["device_name"] = torch.cuda.get_device_name(0)
            info["vram_total_gb"] = round(
                torch.cuda.get_device_properties(0).total_mem / (1024**3), 1
            )
            info["backend"] = "ROCm" if hasattr(torch.version, "hip") and torch.version.hip else "CUDA"
    except ImportError:
        log.debug("torch_not_available")
        pass
    try:
        import cupy
        info["cupy"] = True
        info["cupy_device"] = str(cupy.cuda.Device(0))
    except (ImportError, Exception):
        info["cupy"] = False
    return info


class PipelineProfiler:
    """Collects timing data across an entire pipeline run.

    Thread-safe. Use as a singleton per pipeline execution.

    Usage:
        profiler = PipelineProfiler("full_pipeline")
        with profiler.stage("dem_generation"):
            generate_dem(...)
        with profiler.stage("derivatives", parent="processing"):
            compute_derivatives(...)
        profiler.log_summary()
    """

    def __init__(self, pipeline_name: str = "pipeline"):
        self.pipeline_name = pipeline_name
        self.stages: list[StageResult] = []
        self._lock = threading.Lock()
        self._start_time = time.perf_counter()
        self._start_memory_mb = get_memory_mb()

    @contextmanager
    def stage(
        self,
        name: str,
        parent: str | None = None,
        **metadata: Any,
    ) -> Generator[dict[str, Any], None, None]:
        """Time a pipeline stage. Yields a dict you can add metadata to.

        Example:
            with profiler.stage("fill_difference", parent="detection") as ctx:
                result = pass.run(input)
                ctx["candidates"] = len(result)
        """
        extra: dict[str, Any] = dict(metadata)
        mem_before = get_memory_mb()
        t0 = time.perf_counter()
        try:
            yield extra
        finally:
            elapsed = time.perf_counter() - t0
            mem_after = get_memory_mb()
            extra["memory_delta_mb"] = round(mem_after - mem_before, 1)
            result = StageResult(
                name=name,
                elapsed_s=elapsed,
                parent=parent,
                metadata=extra,
            )
            with self._lock:
                self.stages.append(result)
            log.info(
                "stage_complete",
                stage=name,
                parent=parent,
                elapsed_s=round(elapsed, 3),
                elapsed_ms=round(elapsed * 1000, 1),
                mem_delta_mb=extra["memory_delta_mb"],
                **{k: v for k, v in extra.items() if k != "memory_delta_mb"},
            )

    def record(self, name: str, elapsed_s: float, parent: str | None = None, **metadata: Any) -> None:
        """Manually record a timing (for stages timed externally)."""
        result = StageResult(name=name, elapsed_s=elapsed_s, parent=parent, metadata=metadata)
        with self._lock:
            self.stages.append(result)

    def log_summary(self) -> dict[str, Any]:
        """Log a structured summary of all stages and return it as a dict."""
        total_elapsed = time.perf_counter() - self._start_time
        current_mem = get_memory_mb()

        # Group by parent
        groups: dict[str | None, list[StageResult]] = defaultdict(list)
        for s in self.stages:
            groups[s.parent].append(s)

        # Build summary lines
        lines = [
            f"\n{'='*60}",
            f"  PIPELINE PROFILE: {self.pipeline_name}",
            f"{'='*60}",
        ]

        summary_data: dict[str, Any] = {
            "pipeline": self.pipeline_name,
            "total_elapsed_s": round(total_elapsed, 2),
            "memory_start_mb": round(self._start_memory_mb, 1),
            "memory_end_mb": round(current_mem, 1),
            "cpu_count": get_cpu_count(),
            "stages": {},
        }

        # Top-level stages first (no parent)
        for s in sorted(groups.get(None, []), key=lambda x: x.elapsed_s, reverse=True):
            pct = (s.elapsed_s / total_elapsed * 100) if total_elapsed > 0 else 0
            bar = _bar(pct)
            lines.append(f"  {s.name:<30} {s.elapsed_s:>7.2f}s  {bar} {pct:>5.1f}%")
            summary_data["stages"][s.name] = {
                "elapsed_s": round(s.elapsed_s, 3),
                "pct_of_total": round(pct, 1),
                **s.metadata,
            }

        # Grouped stages
        for parent_name in sorted(k for k in groups if k is not None):
            children = sorted(groups[parent_name], key=lambda x: x.elapsed_s, reverse=True)
            group_total = sum(c.elapsed_s for c in children)
            pct = (group_total / total_elapsed * 100) if total_elapsed > 0 else 0
            lines.append(f"\n  [{parent_name}] total: {group_total:.2f}s ({pct:.1f}%)")
            summary_data["stages"][parent_name] = {"total_s": round(group_total, 3), "children": {}}

            for s in children:
                child_pct = (s.elapsed_s / group_total * 100) if group_total > 0 else 0
                bar = _bar(child_pct, width=15)
                meta_str = ""
                if "candidates" in s.metadata:
                    meta_str = f"  ({s.metadata['candidates']} candidates)"
                lines.append(
                    f"    {s.name:<28} {s.elapsed_s:>7.3f}s  {bar} {child_pct:>5.1f}%{meta_str}"
                )
                summary_data["stages"][parent_name]["children"][s.name] = {
                    "elapsed_s": round(s.elapsed_s, 3),
                    **s.metadata,
                }

        lines.extend([
            f"\n  {'─'*56}",
            f"  Total wall time:   {total_elapsed:>7.2f}s",
            f"  Memory:            {self._start_memory_mb:.0f} MB → {current_mem:.0f} MB "
            f"(Δ {current_mem - self._start_memory_mb:+.0f} MB)",
            f"  CPUs available:    {get_cpu_count()}",
            f"{'='*60}\n",
        ])

        log.info("pipeline_profile", **summary_data)
        # Also print the human-readable table
        print("\n".join(lines))
        return summary_data


def _bar(pct: float, width: int = 20) -> str:
    """Render a simple ASCII progress bar."""
    filled = int(pct / 100 * width)
    return f"[{'█' * filled}{'░' * (width - filled)}]"


def timed(stage_name: str | None = None, parent: str | None = None):
    """Decorator to log execution time of a function.

    Usage:
        @timed("fill_depressions", parent="derivatives")
        def fill_depressions(dem, out):
            ...
    """
    def decorator(fn):
        name = stage_name or fn.__qualname__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            mem_before = get_memory_mb()
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                elapsed = time.perf_counter() - t0
                mem_after = get_memory_mb()
                log.info(
                    "fn_complete",
                    fn=name,
                    parent=parent,
                    elapsed_s=round(elapsed, 3),
                    elapsed_ms=round(elapsed * 1000, 1),
                    mem_delta_mb=round(mem_after - mem_before, 1),
                )
                return result
            except Exception:
                elapsed = time.perf_counter() - t0
                log.error("fn_failed", fn=name, elapsed_s=round(elapsed, 3))
                raise

        return wrapper
    return decorator


# Global profiler instance for the current pipeline run.
# Reset via new_profiler() at the start of each pipeline execution.
_current_profiler: PipelineProfiler | None = None
_profiler_lock = threading.Lock()


def new_profiler(name: str = "pipeline") -> PipelineProfiler:
    """Create and set a new global profiler."""
    global _current_profiler
    with _profiler_lock:
        _current_profiler = PipelineProfiler(name)
        return _current_profiler


def get_profiler() -> PipelineProfiler | None:
    """Get the current global profiler (if any)."""
    return _current_profiler
