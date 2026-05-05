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

    def list_cameras(self, organization_id: int | None = None) -> list[dict]:
        params: dict[str, Any] = {}
        if organization_id is not None:
            params["organization_id"] = organization_id
        return self._get("cameras", params=params or None)

    def get_camera(self, camera_id: int) -> dict:
        return self._get(f"cameras/{camera_id}")

    def get_scores(
        self,
        day: date | str,
        camera_id: int | None = None,
        organization_id: int | None = None,
    ) -> list[dict]:
        """Return persisted FWI scores for a single day.

        Args:
            day: ISO ``YYYY-MM-DD`` string or ``date`` (UTC).
            camera_id: filter to a single camera id.
            organization_id: filter to one organization.
        """
        params: dict[str, Any] = {}
        if camera_id is not None:
            params["camera_id"] = camera_id
        if organization_id is not None:
            params["organization_id"] = organization_id
        return self._get(f"scores/{day}", params=params or None)

    def compute_risk(
        self,
        lat: float,
        lon: float,
        day: date | str | None = None,
    ) -> dict:
        """Compute the FWI risk for an arbitrary (lat, lon).

        Stateless — nothing is persisted. ``day`` defaults to today (UTC)
        server-side.
        """
        params: dict[str, Any] = {"lat": lat, "lon": lon}
        if day is not None:
            params["date"] = str(day)
        return self._get("risk", params=params)

    def recompute_scores(
        self,
        start: date | str,
        end: date | str,
        organization_id: int | None = None,
    ) -> dict:
        """Schedule a recompute over a date range.

        Targets every loaded camera by default, or only the cameras of one
        organization when ``organization_id`` is given. Returns immediately
        (HTTP 202); the work runs in the server scheduler.
        """
        params: dict[str, Any] = {"start": str(start), "end": str(end)}
        if organization_id is not None:
            params["organization_id"] = organization_id
        resp = requests.post(
            urljoin(self.host, "scores/recompute"),
            params=params,
            auth=self.auth,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
