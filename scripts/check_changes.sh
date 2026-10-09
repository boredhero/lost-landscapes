#!/usr/bin/env bash
# Fast local regression gate for investigations/scanning. No downloads or live services.
set -euo pipefail
cd "$(dirname "$0")/.."
timeout --kill-after=5s 15s uvx --offline ruff==0.15.7 check src tests
timeout --kill-after=5s 45s .venv/bin/python -m pytest tests/unit/test_job_control.py tests/unit/test_measurements.py tests/unit/test_context_sources.py -q
timeout --kill-after=5s 15s npm --prefix frontend test
timeout --kill-after=5s 30s npm --prefix frontend run lint -- --max-warnings 0
timeout --kill-after=5s 30s npm --prefix frontend run build
