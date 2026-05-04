from datetime import date
from typing import Any
from urllib.parse import urljoin

import requests


class Client:
    """HTTP client for the Pyronear risk API.

    Args:
        host: base URL of the API, e.g. ``https://riskapi.pyronear.org``.
        username: HTTP basic-auth username (the ``API_USERNAME`` of the server).
        password: HTTP basic-auth password (the ``API_PASSWORD`` of the server).
        timeout: per-request timeout in seconds.
    """

    def __init__(self, host: str, username: str, password: str, timeout: int = 10) -> None:
        self.host = host if host.endswith("/") else host + "/"
        self.auth = (username, password)
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = requests.get(
            urljoin(self.host, path.lstrip("/")),
            params=params,
            auth=self.auth,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def health(self) -> dict:
        return self._get("health")

    def list_cameras(self) -> list[dict]:
        return self._get("cameras")

    def get_camera(self, camera_id: int) -> dict:
        return self._get(f"cameras/{camera_id}")

    def get_scores(
        self,
        day: date | str,
        camera_id: int | None = None,
    ) -> list[dict]:
        """Return persisted FWI scores for a single day.

        Args:
            day: ISO ``YYYY-MM-DD`` string or ``date`` (UTC).
            camera_id: filter to a single camera id.
        """
        params: dict[str, Any] = {}
        if camera_id is not None:
            params["camera_id"] = camera_id
        return self._get(f"scores/{day}", params=params or None)

    def recompute_scores(self, start: date | str, end: date | str) -> dict:
        """Schedule a recompute over a date range for every loaded camera.

        Returns immediately (HTTP 202); the work runs in the server scheduler.
        """
        resp = requests.post(
            urljoin(self.host, "scores/recompute"),
            params={"start": str(start), "end": str(end)},
            auth=self.auth,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
