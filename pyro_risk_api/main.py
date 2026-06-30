import logging
from contextlib import asynccontextmanager
from datetime import date as date_, datetime, timedelta, timezone
import json 
import os

import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from pyro_risk_api.api import cameras, health, risk, scores
from pyro_risk_api.core.config import settings
from pyro_risk_api.core.db import SessionLocal, init_db
from pyro_risk_api.core.fwi import fwi_class, query_fwi
from pyro_risk_api.core.pyro_client import build_client
from pyro_risk_api.models.fwi_score import FWIScore

logger = logging.getLogger(__name__)

CAMERA_FIELDS = ("id", "name", "organization_id", "lat", "lon")


def _compute_fwi_for_cams(cams: list[dict], day: date_) -> dict[int, tuple[float | None, str | None]]:
    """Return ``{camera_id: (fwi, fwi_class)}`` for every camera in ``cams``.

    Each unique ``(lat, lon)`` is queried at most once: cameras sharing a
    location reuse the cached value. ``None`` covers both transport errors
    and EFFIS nodata.
    """
    cache: dict[tuple[float, float], float | None] = {}
    out: dict[int, tuple[float | None, str | None]] = {}
    for cam in cams:
        key = (cam["lat"], cam["lon"])
        if key not in cache:
            try:
                cache[key] = query_fwi(cam["lat"], cam["lon"], day)
            except (requests.RequestException, RuntimeError) as exc:
                logger.warning(
                    "FWI query failed lat=%s lon=%s day=%s: %s", key[0], key[1], day, exc
                )
                cache[key] = None
        value = cache[key]
        out[cam["id"]] = (
            (round(value, 3), fwi_class(value)) if value is not None else (None, None)
        )
    if cams:
        logger.info(
            "FWI day=%s: %d cameras → %d unique locations queried",
            day, len(cams), len(cache),
        )
    return out


def _enrich_with_fwi(cameras_raw: list[dict], now: datetime) -> list[dict]:
    today = now.date()
    fwi_by_id = _compute_fwi_for_cams(cameras_raw, today)
    enriched: list[dict] = []
    for cam in cameras_raw:
        row = {k: cam.get(k) for k in CAMERA_FIELDS}
        row["fwi"], row["fwi_class"] = fwi_by_id[cam["id"]]
        row["last_refresh_at"] = now.isoformat(timespec="seconds")
        enriched.append(row)
    return enriched


def _upsert_scores(payload: list[dict]) -> None:
    if not payload:
        return
    with SessionLocal() as session:
        stmt = sqlite_insert(FWIScore).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["camera_id", "date"],
            set_={"fwi": stmt.excluded.fwi, "fwi_class": stmt.excluded.fwi_class, "fetched_at": stmt.excluded.fetched_at},
        )
        session.execute(stmt)
        session.commit()


def _persist_scores(enriched: list[dict], now: datetime) -> None:
    if not enriched:
        return
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
    _upsert_scores(payload)
    logger.info("persisted %d FWI scores for %s", len(payload), today.isoformat())


def compute_and_persist_day(cams: list[dict], day: date_) -> int:
    """Compute FWI for ``cams`` on ``day`` and upsert successful samples.

    Failed lookups (transport error, EFFIS error, or nodata) are skipped so
    they don't overwrite previously persisted values. Cameras sharing the
    same ``(lat, lon)`` reuse one EFFIS query. Returns the number of rows
    written.
    """
    if not cams:
        return 0
    now = datetime.now(timezone.utc)
    fwi_by_id = _compute_fwi_for_cams(cams, day)
    payload: list[dict] = []
    for cam in cams:
        fwi, cls = fwi_by_id[cam["id"]]
        if fwi is None:
            continue
        payload.append({
            "camera_id": cam["id"],
            "date": day,
            "fwi": fwi,
            "fwi_class": cls,
            "fetched_at": now,
        })
    _upsert_scores(payload)
    return len(payload)


def recompute_range(cams: list[dict], start: date_, end: date_) -> None:
    if not cams:
        logger.warning("recompute aborted: empty camera set")
        return
    total = 0
    skipped = 0
    day = start
    while day <= end:
        written = compute_and_persist_day(cams, day)
        day_skipped = len(cams) - written
        logger.info(
            "recomputed %d scores for %s (skipped %d)",
            written, day.isoformat(), day_skipped,
        )
        total += written
        skipped += day_skipped
        day += timedelta(days=1)
    logger.info("recompute done: %d scores written, %d skipped, %s → %s", total, skipped, start, end)


def refresh_cameras(app):
    try:
        print("Chargement forcé des caméras depuis le fichier local...")
        
        # Cette ligne trouve automatiquement le dossier où est installé main.py
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # On remonte d'un niveau si main.py est dans pyro_risk_api/ et le json à la racine
        # Si ton fichier json est dans le même dossier que main.py, utilise juste : 
        # file_path = os.path.join(current_dir, "sample_cameras.json")
        file_path = os.path.join(current_dir, "..", "sample_cameras.json")
        
        # Si jamais le fichier est directement à côté de main.py et pas au-dessus :
        if not os.path.exists(file_path):
            file_path = os.path.join(current_dir, "sample_cameras.json")

        print(f"Tentative de lecture du fichier à l'adresse : {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            cameras = json.load(f)
        
        app.state.cameras = cameras 
        print(f"Succès : {len(cameras)} caméras chargées en mémoire.")
        
    except Exception as e:
        print("failed to refresh cameras")
        print(f"Détail de l'erreur : {e}")

#def refresh_cameras(app: FastAPI) -> None:
#    try:
#        now = datetime.now(timezone.utc)
#        client = build_client()
#        raw = client.fetch_cameras().json()
#        logger.info("fetched %d cameras from %s", len(raw), settings.pyro_api_host)
#        enriched = _enrich_with_fwi(raw, now)
#        app.state.cameras = enriched
#        logger.info("FWI computed for %d cameras", len(enriched))
#        _persist_scores(enriched, now)
#    except Exception:
#        logger.exception("failed to refresh cameras")


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
app.include_router(risk.router)