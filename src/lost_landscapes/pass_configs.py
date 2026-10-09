"""Resolve bundled analysis configurations independently of native-tool cwd changes."""

import re
from pathlib import Path

from lost_landscapes.config import settings

_ROOTS = (
    Path(__file__).resolve().parents[2] / "configs" / "passes",
    Path("/app/configs/passes"),
    (settings.data_dir.parent / "configs" / "passes").resolve(),
)


def pass_config_path(name: str) -> Path:
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise ValueError("Unknown analysis configuration")
    for root in _ROOTS:
        candidate = root / f"{name}.toml"
        if candidate.is_file():
            return candidate
    raise ValueError("Unknown analysis configuration")
