import json
from urllib.parse import urljoin

import requests
from pyroclient import Client

from pyro_risk_api.core.config import settings


def login() -> str:
    resp = requests.post(
        urljoin(settings.pyro_api_host, "api/v1/login/creds"),
        data={"username": settings.pyro_api_username, "password": settings.pyro_api_password},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def build_client() -> Client:
    return Client(token=login(), host=settings.pyro_api_host)


def load_cameras() -> list[dict]:
    """Return raw camera dicts from the configured source.

    If ``settings.cameras_file`` is set, cameras are read from that local
    JSON file (no credentials needed); otherwise they are fetched from the
    live API.
    """
    if settings.cameras_file:
        with settings.cameras_file.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("CAMERAS_FILE must contain a JSON list of cameras")
        return data
    return build_client().fetch_cameras().json()
