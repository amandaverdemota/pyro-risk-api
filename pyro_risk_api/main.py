import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from pyro_risk_api.api import cameras, health, scores
from pyro_risk_api.core.config import settings
from pyro_risk_api.core.db import SessionLocal, init_db
from pyro_risk_api.core.fwi import fwi_class, query_fwi
from pyro_risk_api.core.pyro_client import build_client
from pyro_risk_api.models.fwi_score import FWIScore

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


def _persist_scores(enriched: list[dict]) -> None:
    if not enriched:
        return
    now = datetime.now(timezone.utc)
    today = now.date()
    payload = [
        {
            "camera_id": cam["id"],
            "date": today,
            "fwi": cam["fwi"],
            "fwi_class": cam["fwi_class"],
            "fetched_at": now,
        }
        for cam in enriched
    ]
    with SessionLocal() as session:
        stmt = sqlite_insert(FWIScore).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["camera_id", "date"],
            set_={"fwi": stmt.excluded.fwi, "fwi_class": stmt.excluded.fwi_class, "fetched_at": stmt.excluded.fetched_at},
        )
        session.execute(stmt)
        session.commit()
    logger.info("persisted %d FWI scores for %s", len(payload), today.isoformat())


def refresh_cameras(app: FastAPI) -> None:
    try:
        client = build_client()
        raw = client.fetch_cameras().json()
        logger.info("fetched %d cameras from %s", len(raw), settings.pyro_api_host)
        enriched = _enrich_with_fwi(raw)
        app.state.cameras = enriched
        logger.info("FWI computed for %d cameras", len(enriched))
        _persist_scores(enriched)
    except Exception:
        logger.exception("failed to refresh cameras")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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
app.include_router(scores.router)
