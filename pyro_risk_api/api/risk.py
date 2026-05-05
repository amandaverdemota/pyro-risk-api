from datetime import date as date_, datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from pyro_risk_api.core.auth import require_basic_auth
from pyro_risk_api.core.fwi import fwi_class, query_fwi

router = APIRouter(tags=["risk"], dependencies=[Depends(require_basic_auth)])


class RiskPoint(BaseModel):
    lat: float
    lon: float
    date: date_
    fwi: float | None
    fwi_class: str | None
    fetched_at: datetime


@router.get("/risk", response_model=RiskPoint)
def compute_risk(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    date: date_ | None = Query(None, description="UTC date; defaults to today"),
) -> RiskPoint:
    now = datetime.now(timezone.utc)
    day = date or now.date()
    try:
        value = query_fwi(lat, lon, day)
    except (requests.RequestException, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=f"EFFIS query failed: {exc}") from exc

    return RiskPoint(
        lat=lat,
        lon=lon,
        date=day,
        fwi=round(value, 3) if value is not None else None,
        fwi_class=fwi_class(value) if value is not None else None,
        fetched_at=now,
    )
