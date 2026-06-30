from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from pyro_risk_api.core.auth import require_basic_auth

router = APIRouter(tags=["cameras"])


class Camera(BaseModel):
    id: int
    name: str
    organization_id: int
    lat: float
    lon: float
    fwi: float | None = None
    fwi_class: str | None = None
    last_refresh_at: datetime | None = None


@router.get("/cameras", response_model=list[Camera])
def list_cameras(
    request: Request,
    organization_id: int | None = Query(None, description="Filter to a single organization"),
) -> list[Camera]:
    cameras = request.app.state.cameras
    if cameras is None:
        raise HTTPException(status_code=503, detail="cameras not loaded")
    if organization_id is not None:
        cameras = [c for c in cameras if c["organization_id"] == organization_id]
    return [Camera(**cam) for cam in cameras]


@router.get("/cameras/{camera_id}", response_model=Camera)
def get_camera(camera_id: int, request: Request) -> Camera:
    cameras = request.app.state.cameras
    if cameras is None:
        raise HTTPException(status_code=503, detail="cameras not loaded")
    for cam in cameras:
        if cam["id"] == camera_id:
            return Camera(**cam)
    raise HTTPException(status_code=404, detail=f"camera {camera_id} not found")
