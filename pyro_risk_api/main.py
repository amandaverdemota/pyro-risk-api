import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from pyro_risk_api.api import cameras, health
from pyro_risk_api.core.config import settings
from pyro_risk_api.core.fwi import fwi_class, query_fwi
from pyro_risk_api.core.pyro_client import build_client

logger = logging.getLogger(__name__)

CAMERA_FIELDS = ("id", "name", "organization_id", "lat", "lon")


def _enrich_with_fwi(cameras_raw: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    today = now.date()
    enriched: list[dict] = []
    for cam in cameras_raw:
        row = {k: cam.get(k) for k in CAMERA_FIELDS}
        try:
            value = query_fwi(cam["lat"], cam["lon"], today)
            row["fwi"] = round(value, 3) if value is not None else None
            row["fwi_class"] = fwi_class(value) if value is not None else None
        except (requests.RequestException, RuntimeError) as exc:
            logger.warning("FWI query failed for camera %s: %s", cam.get("id"), exc)
            row["fwi"] = None
            row["fwi_class"] = None
        row["last_refresh_at"] = now.isoformat(timespec="seconds")
        enriched.append(row)
    return enriched


def refresh_cameras(app: FastAPI) -> None:
    try:
        client = build_client()
        raw = client.fetch_cameras().json()
        logger.info("fetched %d cameras from %s", len(raw), settings.pyro_api_host)
        app.state.cameras = _enrich_with_fwi(raw)
        logger.info("FWI computed for %d cameras", len(app.state.cameras))
    except Exception:
        logger.exception("failed to refresh cameras")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.cameras = None

    scheduler = AsyncIOScheduler(timezone=settings.cameras_refresh_timezone)
    scheduler.add_job(refresh_cameras, args=[app], id="initial_refresh")
    scheduler.add_job(
        refresh_cameras,
        CronTrigger(
            hour=settings.cameras_refresh_cron_hour,
            minute=settings.cameras_refresh_cron_minute,
            timezone=settings.cameras_refresh_timezone,
        ),
        args=[app],
        id="refresh_cameras",
        replace_existing=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "scheduled cameras refresh at %02d:%02d %s",
        settings.cameras_refresh_cron_hour,
        settings.cameras_refresh_cron_minute,
        settings.cameras_refresh_timezone,
    )

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
app.include_router(health.router)
app.include_router(cameras.router)
