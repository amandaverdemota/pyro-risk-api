from datetime import date as date_, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from pyro_risk_api.core.auth import require_basic_auth
from pyro_risk_api.core.db import SessionLocal
from pyro_risk_api.models.fwi_score import FWIScore

router = APIRouter(tags=["scores"], dependencies=[Depends(require_basic_auth)])


class Score(BaseModel):
    camera_id: int
    date: date_
    fwi: float | None
    fwi_class: str | None
    fetched_at: datetime


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class RecomputeAck(BaseModel):
    status: str
    start: date_
    end: date_
    cameras: int
    days: int


@router.post("/scores/recompute", response_model=RecomputeAck, status_code=status.HTTP_202_ACCEPTED)
def recompute_scores(
    request: Request,
    start: date_ = Query(..., description="Inclusive start date (UTC)"),
    end: date_ = Query(..., description="Inclusive end date (UTC)"),
) -> RecomputeAck:
    if end < start:
        raise HTTPException(status_code=400, detail="end is before start")
    cams = request.app.state.cameras
    if not cams:
        raise HTTPException(status_code=503, detail="cameras not loaded yet")

    from pyro_risk_api.main import recompute_range  # avoid circular import at module load

    scheduler = request.app.state.scheduler
    scheduler.add_job(
        recompute_range,
        args=[request.app, start, end],
        id=f"recompute-{start}-{end}",
        replace_existing=True,
    )
    return RecomputeAck(
        status="scheduled",
        start=start,
        end=end,
        cameras=len(cams),
        days=(end - start).days + 1,
    )


@router.get("/scores/{day}", response_model=list[Score])
def list_scores(
    day: date_,
    camera_id: int | None = Query(None, description="Filter to a single camera"),
    session: Session = Depends(get_session),
) -> list[Score]:
    stmt = select(FWIScore).where(FWIScore.date == day)
    if camera_id is not None:
        stmt = stmt.where(FWIScore.camera_id == camera_id)
    stmt = stmt.order_by(FWIScore.camera_id)

    rows = session.scalars(stmt).all()
    out: list[Score] = []
    for r in rows:
        fetched_at = r.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        out.append(Score(
            camera_id=r.camera_id,
            date=r.date,
            fwi=r.fwi,
            fwi_class=r.fwi_class,
            fetched_at=fetched_at,
        ))
    return out
