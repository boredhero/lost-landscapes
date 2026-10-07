FROM pdal/pdal:latest

# pdal/pdal already has: PDAL 2.10, GDAL 3.12, Python 3.13, Ubuntu 24.04
# Just need: pip/uv, libspatialindex (for rtree), and our Python deps

RUN apt-get update && apt-get install -y --no-install-recommends \
    libspatialindex-dev \
    osmium-tool \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install Python deps — inject version from info.yml (single source of truth)
COPY pyproject.toml uv.lock info.yml ./
COPY README.md ./
RUN VERSION=$(grep '^version:' info.yml | awk '{print $2}') && sed -i "s/__LOSTLANDSCAPES_VERSION__/$VERSION/" pyproject.toml
RUN uv sync --frozen --no-dev --no-editable

# Force WhiteboxTools binary download (the whitebox Python package downloads
# the WBT Rust binary on first import — do it at build time, not runtime)
RUN uv run python -c "import whitebox; wbt = whitebox.WhiteboxTools(); print('WBT version:', wbt.version().split(chr(10))[0])"

# Copy source
COPY src/ src/
COPY configs/ configs/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY scripts/ scripts/
COPY tests/fixtures/known_sites.json tests/fixtures/known_sites.json

# Copy built frontend (injected by CI)
COPY frontend/dist/ static/

# Log directory
RUN mkdir -p /app/logs
VOLUME /app/logs

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "lost_landscapes.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
