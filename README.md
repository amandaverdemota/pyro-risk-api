# pyro-risk-api

FastAPI service that exposes Pyronear cameras enriched with a daily fire-risk
score. Cameras are pulled from the upstream
[pyronear/pyro-api](https://github.com/pyronear/pyro-api) on startup and
refreshed every night at 02:00 UTC (configurable). All timestamps emitted by
the API are UTC. For each camera, the current-day
[FWI (Fire Weather Index)](https://effis.jrc.ec.europa.eu/about-effis/technical-background/fire-danger-forecast)
is sampled from the Copernicus EFFIS WMS layer (`mf010.fwi`, Météo-France 10 km).

## Endpoints

| Method | Path                                | Auth   | Description                                          |
|--------|-------------------------------------|--------|------------------------------------------------------|
| GET    | `/health`                           | none   | Liveness probe                                       |
| GET    | `/cameras?organization_id=…`        | basic  | List cameras with current FWI; `organization_id` filter is optional |
| GET    | `/cameras/{id}`                     | basic  | Single camera by id                                  |
| GET    | `/scores/{date}?camera_id=…&organization_id=…` | basic | Persisted scores for a single day; both filters optional. Cameras missing for `date` are computed and persisted on the fly before the response is returned |
| GET    | `/risk?lat=…&lon=…&date=…`         | basic  | One-shot FWI lookup for an arbitrary point (no persistence); `date` defaults to today UTC |
| POST   | `/scores/recompute?start=…&end=…&organization_id=…` | basic | Schedule a recompute over `[start, end]`; restrict to one org if given. Returns 202; runs in background |
| GET    | `/docs`                             | none   | OpenAPI / Swagger UI                                 |

Each camera payload:

```json
{
  "id": 1,
  "name": "mateo-camera-01",
  "organization_id": 2,
  "lat": 48.4267,
  "lon": 2.7109,
  "fwi": 0.0,
  "fwi_class": "very_low",
  "last_refresh_at": "2026-05-04T15:32:05Z"
}
```

`fwi_class` follows the EFFIS European danger classes: `very_low`, `low`,
`moderate`, `high`, `very_high`, `extreme`.

## Configuration

All settings are read from environment variables (or a local `.env` file —
not committed). See `.env.example`:

| Variable                       | Description                                   | Default                              |
|--------------------------------|-----------------------------------------------|--------------------------------------|
| `API_USERNAME`                 | Basic-auth user for protected routes          | _required_                           |
| `API_PASSWORD`                 | Basic-auth password for protected routes      | _required_                           |
| `PYRO_API_HOST`                | Upstream pyro-api host                        | `https://alertapi.pyronear.org/`     |
| `PYRO_API_USERNAME`            | Upstream pyro-api username                    | _required unless `CAMERAS_FILE` set_ |
| `PYRO_API_PASSWORD`            | Upstream pyro-api password                    | _required unless `CAMERAS_FILE` set_ |
| `CAMERAS_FILE`                 | Load cameras from a local JSON file (no creds); a bundled `sample_cameras.json` with anonymized positions is provided | _unset (use live API)_ |
| `CAMERAS_REFRESH_CRON_HOUR`    | Daily refresh hour (UTC by default)           | `2`                                  |
| `CAMERAS_REFRESH_CRON_MINUTE`  | Daily refresh minute                          | `0`                                  |
| `CAMERAS_REFRESH_TIMEZONE`     | IANA timezone for the schedule                | `UTC`                                |
| `DATABASE_URL`                 | SQLAlchemy URL for score persistence          | `sqlite:///./data/pyro_risk.db`      |

The `/cameras` endpoints are protected with HTTP Basic auth; `/health` is left
public so container orchestrators can probe it.

## Run locally

Uses [uv](https://docs.astral.sh/uv/). Install it if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
uv venv
uv pip install -r requirements.txt

cp .env.example .env  # runs creds-free by default (bundled sample cameras)
uv run uvicorn pyro_risk_api.main:app --reload
```

Then:

```bash
curl http://127.0.0.1:8000/health
curl -u admin:changeme http://127.0.0.1:8000/cameras
```

## Run with Docker

The compose file ships a Traefik reverse proxy that terminates TLS via
Let's Encrypt (TLS-ALPN challenge on port 443) and exposes only the API on
the public domain.

```bash
docker compose up -d --build
```

For a quick local run without Traefik, build and run the image directly:

```bash
docker build -t pyro-risk-api .
docker run --rm -p 8000:8000 --env-file .env pyro-risk-api
```

The image is multi-stage (Python 3.12 slim), runs as a non-root user, and
ships a `HEALTHCHECK` hitting `/health`.

## Deployment

The compose stack is meant to run on a single VPS:

1. Point a DNS A record for `API_DOMAIN` (default `riskapi.pyronear.org`) at
   the server's public IP (e.g. `57.128.107.129`).
2. Open ports `80` and `443` on the host firewall.
3. Set `LETSENCRYPT_EMAIL` and the auth credentials in `.env`.
4. `docker compose up -d --build` — Traefik will request a certificate on the
   first request to `https://${API_DOMAIN}`.

## Python client

A tiny client lives at [`client/`](./client) and is published as
`pyroriskclient`. Install with:

```bash
uv pip install "git+https://github.com/MateoLostanlen/pyro-risk-api.git#subdirectory=client"
```

```python
from pyroriskclient import Client

api = Client(host="https://riskapi.pyronear.org", username="admin", password="...")
api.list_cameras()
api.get_scores("2026-05-04", camera_id=1)
```

See [`client/README.md`](./client/README.md) for the full surface.

## Project layout

```
pyro_risk_api/
├── main.py              # FastAPI app, lifespan, APScheduler job
├── api/
│   ├── health.py        # GET /health
│   ├── cameras.py       # GET /cameras, GET /cameras/{id} (auth-protected)
│   ├── scores.py        # GET /scores/{date} (single day, optional camera filter)
│   └── risk.py          # GET /risk (stateless lat/lon + date lookup)
├── core/
│   ├── config.py        # pydantic-settings, .env loader
│   ├── auth.py          # Basic-auth dependency
│   ├── db.py            # SQLAlchemy engine + session factory
│   ├── pyro_client.py   # Upstream pyro-api login + client factory
│   └── fwi.py           # EFFIS WMS sampling, FWI class buckets
└── models/
    └── fwi_score.py     # FWIScore table (camera_id, date, fwi, fwi_class)
```

## How the refresh works

1. On startup the lifespan calls `refresh_cameras(app)`:
   - Loads the camera list: from the local `CAMERAS_FILE` JSON if set
     (no credentials needed), otherwise logs in to `PYRO_API_HOST` via
     `POST /api/v1/login/creds` and calls `pyroclient.Client.fetch_cameras()`.
   - For each camera, samples today's FWI from EFFIS and stores
     `(id, name, organization_id, lat, lon, fwi, fwi_class, last_refresh_at)`
     in `app.state.cameras`.
2. An `AsyncIOScheduler` (APScheduler) re-runs the same function every day at
   the configured hour/minute in the configured timezone.
3. Each refresh upserts one `(camera_id, date)` row per camera into the
   `fwi_score` table — historical scores accumulate over time.
4. `GET /scores/{date}` lazily fills the cache: any camera missing for the
   requested date is computed and persisted before the response is returned.
   This means the first read of an unseen date is slow (one EFFIS query per
   missing camera) but subsequent reads are instant.
