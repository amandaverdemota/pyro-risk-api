from datetime import date as date_, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from pyro_risk_api.core.auth import require_basic_auth
from pyro_risk_api.core.db import SessionLocal
from pyro_risk_api.models.fwi_score import FWIScore

router = APIRouter(tags=["scores"])


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
    organization_id: int | None = Query(None, description="Restrict recompute to one organization"),
) -> RecomputeAck:
    if end < start:
        raise HTTPException(status_code=400, detail="end is before start")
    cams = request.app.state.cameras
    if not cams:
        raise HTTPException(status_code=503, detail="cameras not loaded yet")
    if organization_id is not None:
        cams = [c for c in cams if c["organization_id"] == organization_id]
        if not cams:
            raise HTTPException(status_code=404, detail=f"no camera in org {organization_id}")

    from pyro_risk_api.main import recompute_range  # avoid circular import at module load

    scheduler = request.app.state.scheduler
    job_id = f"recompute-{start}-{end}" + (f"-org{organization_id}" if organization_id is not None else "")
    scheduler.add_job(
        recompute_range,
        args=[cams, start, end],
        id=job_id,
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
    request: Request,
    camera_id: int | None = Query(None, description="Filter to a single camera"),
    organization_id: int | None = Query(None, description="Filter to a single organization"),
    session: Session = Depends(get_session),
) -> list[Score]:
    cams_state = request.app.state.cameras
    has_filter = camera_id is not None or organization_id is not None
    if has_filter and cams_state is None:
        raise HTTPException(status_code=503, detail="cameras not loaded yet")

    target_cams = list(cams_state) if cams_state is not None else []
    if camera_id is not None:
        target_cams = [c for c in target_cams if c["id"] == camera_id]
    if organization_id is not None:
        target_cams = [c for c in target_cams if c["organization_id"] == organization_id]
    if has_filter and not target_cams:
        return []

    target_ids = [c["id"] for c in target_cams]

    # Compute on the fly the cameras that don't yet have a score for `day`.
    if target_cams:
        existing_ids = set(session.scalars(
            select(FWIScore.camera_id).where(
                FWIScore.date == day, FWIScore.camera_id.in_(target_ids)
            )
        ).all())
        missing_cams = [c for c in target_cams if c["id"] not in existing_ids]
        if missing_cams:
            from pyro_risk_api.main import compute_and_persist_day  # avoid circular import

            compute_and_persist_day(missing_cams, day)

    stmt = select(FWIScore).where(FWIScore.date == day)
    if target_ids:
        stmt = stmt.where(FWIScore.camera_id.in_(target_ids))
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
