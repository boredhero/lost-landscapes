"""Small, independent visit store. No analysis database or raw identifiers required."""

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from lost_landscapes.config import settings
from lost_landscapes.utils.log_manager import log

router = APIRouter(prefix="/visits", tags=["visits"])


class Visit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    browser_id: UUID
    visit_id: UUID


def connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=0.25)
    db.execute("CREATE TABLE IF NOT EXISTS visits (day TEXT NOT NULL, visit TEXT NOT NULL, "
               "browser TEXT NOT NULL, PRIMARY KEY(day, visit))")
    return db


def record_visit(path: Path, visit: Visit, now: datetime | None = None):
    now = now or datetime.now(UTC)
    day = now.date().isoformat()
    # Daily hashes prevent joining browser activity across days in the stored data.
    def digest(value):
        return hashlib.sha256(f"{day}:{value}".encode()).hexdigest()

    db = connect(path)
    try:
        with db:
            db.execute("DELETE FROM visits WHERE day < ?", ((now.date() - timedelta(days=89)).isoformat(),))
            added = db.execute("INSERT OR IGNORE INTO visits VALUES (?, ?, ?)",
                               (day, digest(visit.visit_id), digest(visit.browser_id))).rowcount
            count, browsers = db.execute("SELECT COUNT(*), COUNT(DISTINCT browser) FROM visits WHERE day=?", (day,)).fetchone()
        return {"day": day, "visits": count, "browsers": browsers, "added": bool(added)}
    finally:
        db.close()


def report(path: Path, days: int = 30):
    if not path.exists():
        return []
    # Reporting never creates or changes the store.
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=0.25)
    try:
        cutoff = (datetime.now(UTC).date() - timedelta(days=min(max(days, 1), 90) - 1)).isoformat()
        return [dict(zip(("day", "visits", "browsers"), row, strict=True)) for row in db.execute(
            "SELECT day, COUNT(*), COUNT(DISTINCT browser) FROM visits WHERE day >= ? GROUP BY day ORDER BY day DESC", (cutoff,))]
    finally:
        db.close()


@router.post("", status_code=204)
def visit(body: Visit, request: Request):
    if request.headers.get("DNT") == "1" or request.headers.get("Sec-GPC") == "1":
        return Response(status_code=204)
    try:
        counts = record_visit(settings.data_dir / "analytics" / "visits.sqlite3", body)
    except (OSError, sqlite3.Error) as exc:
        log.warning("visit_store_unavailable", error_type=type(exc).__name__)
        raise HTTPException(503, "Visit counter unavailable") from exc
    log.info("anonymous_visit_counts", **counts)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily UTC visit counts (approximate browsers, not people)")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(report(settings.data_dir / "analytics" / "visits.sqlite3", args.days), indent=2))
