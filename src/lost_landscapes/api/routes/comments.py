"""Comment and saved detection endpoints."""

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.api.deps import get_db
from lost_landscapes.db.models import Comment, Detection, SavedDetection
from lost_landscapes.utils.log_manager import log

router = APIRouter(tags=["comments"])


class CommentCreate(BaseModel):
    text: str
    author: str | None = None


class SaveCreate(BaseModel):
    label: str | None = None
    color: str | None = None
    notes: str | None = None


# --- Comments ---

@router.get("/detections/{detection_id}/comments")
async def list_comments(
    detection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    log.debug("list_comments_requested", detection_id=str(detection_id))
    t0 = time.perf_counter()
    stmt = (
        select(Comment)
        .where(Comment.detection_id == detection_id)
        .order_by(Comment.created_at.desc())
    )
    result = await db.execute(stmt)
    comments = result.scalars().all()
    log.info("comments_listed", detection_id=str(detection_id), count=len(comments), elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    return [
        {
            "id": str(c.id),
            "text": c.text,
            "author": c.author,
            "created_at": str(c.created_at),
        }
        for c in comments
    ]


@router.post("/detections/{detection_id}/comments")
async def add_comment(
    detection_id: uuid.UUID,
    body: CommentCreate,
    db: AsyncSession = Depends(get_db),
):
    log.info("add_comment_requested", detection_id=str(detection_id), author=body.author)
    detection = await db.get(Detection, detection_id)
    if not detection:
        log.warning("add_comment_detection_not_found", detection_id=str(detection_id))
        raise HTTPException(status_code=404, detail="Detection not found")
    comment = Comment(
        detection_id=detection_id,
        text=body.text,
        author=body.author,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    log.info("comment_created", comment_id=str(comment.id), detection_id=str(detection_id), author=body.author)
    return {"id": str(comment.id), "status": "created"}


@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    log.info("delete_comment_requested", comment_id=str(comment_id))
    comment = await db.get(Comment, comment_id)
    if not comment:
        log.warning("delete_comment_not_found", comment_id=str(comment_id))
        raise HTTPException(status_code=404, detail="Comment not found")
    await db.delete(comment)
    await db.commit()
    log.info("comment_deleted", comment_id=str(comment_id))
    return {"status": "deleted"}


# --- Saved/Highlighted Detections ---

@router.get("/saved")
async def list_saved(
    db: AsyncSession = Depends(get_db),
):
    log.debug("list_saved_requested")
    t0 = time.perf_counter()
    stmt = select(SavedDetection).order_by(SavedDetection.created_at.desc()).limit(500)
    result = await db.execute(stmt)
    saves = result.scalars().all()
    log.info("saved_detections_listed", count=len(saves), elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    return [
        {
            "id": str(s.id),
            "detection_id": str(s.detection_id),
            "label": s.label,
            "color": s.color,
            "notes": s.notes,
            "created_at": str(s.created_at),
        }
        for s in saves
    ]


@router.post("/detections/{detection_id}/save")
async def save_detection(
    detection_id: uuid.UUID,
    body: SaveCreate,
    db: AsyncSession = Depends(get_db),
):
    log.info("save_detection_requested", detection_id=str(detection_id), label=body.label)
    detection = await db.get(Detection, detection_id)
    if not detection:
        log.warning("save_detection_not_found", detection_id=str(detection_id))
        raise HTTPException(status_code=404, detail="Detection not found")
    save = SavedDetection(
        detection_id=detection_id,
        label=body.label,
        color=body.color,
        notes=body.notes,
    )
    db.add(save)
    await db.commit()
    await db.refresh(save)
    log.info("detection_saved", save_id=str(save.id), detection_id=str(detection_id), label=body.label)
    return {"id": str(save.id), "status": "saved"}


@router.delete("/saved/{save_id}")
async def unsave_detection(
    save_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    log.info("unsave_detection_requested", save_id=str(save_id))
    save = await db.get(SavedDetection, save_id)
    if not save:
        log.warning("unsave_detection_not_found", save_id=str(save_id))
        raise HTTPException(status_code=404, detail="Saved detection not found")
    await db.delete(save)
    await db.commit()
    log.info("detection_unsaved", save_id=str(save_id))
    return {"status": "removed"}
