from datetime import date as date_, datetime, timezone

from fastapi import APIRouter, Depends, Query
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


@router.get("/scores", response_model=list[Score])
def list_scores(
    start: date_ = Query(..., description="Inclusive start date (YYYY-MM-DD)"),
    end: date_ | None = Query(None, description="Inclusive end date (defaults to today UTC)"),
    camera_id: int | None = Query(None, description="Filter to a single camera"),
    session: Session = Depends(get_session),
) -> list[Score]:
    if end is None:
        end = datetime.now(timezone.utc).date()

    stmt = select(FWIScore).where(FWIScore.date >= start, FWIScore.date <= end)
    if camera_id is not None:
        stmt = stmt.where(FWIScore.camera_id == camera_id)
    stmt = stmt.order_by(FWIScore.date, FWIScore.camera_id)

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
