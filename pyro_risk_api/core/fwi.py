"""Query daily FWI (Fire Weather Index) from Copernicus EFFIS for a location.

EFFIS exposes FWI as a WMS raster layer. The dedicated GetFeatureInfo query layer
(``mf010.query``) is configured server-side with unfilled template placeholders,
so we sample the value by requesting a small GetMap GeoTIFF centered on each
point and reading the center pixel.

Layer: ``mf010.fwi`` — Météo-France 10 km, daily forecast (today + ~3 days).
"""

from __future__ import annotations

import io
from datetime import date

import numpy as np
import requests
from PIL import Image

EFFIS_WMS = "https://maps.effis.emergency.copernicus.eu/effis"
LAYER = "mf010.fwi"

# EFFIS European FWI danger classes
FWI_CLASSES = [
    (5.2, "very_low"),
    (11.2, "low"),
    (21.3, "moderate"),
    (38.0, "high"),
    (50.0, "very_high"),
    (float("inf"), "extreme"),
]


def fwi_class(value: float) -> str:
    for threshold, label in FWI_CLASSES:
        if value < threshold:
            return label
    return "extreme"


def query_fwi(lat: float, lon: float, target_date: date, layer: str = LAYER) -> float | None:
    """Sample the FWI value at (lat, lon) by reading the center pixel of a small
    GeoTIFF. Returns None on nodata. Raises on transport error."""
    half = 0.5
    grid = 11
    params = {
        "service": "WMS",
        "version": "1.1.1",
        "request": "GetMap",
        "layers": layer,
        "styles": "",
        "srs": "EPSG:4326",
        "bbox": f"{lon - half},{lat - half},{lon + half},{lat + half}",
        "width": grid,
        "height": grid,
        "format": "image/tiff",
        "time": target_date.isoformat(),
    }

    resp = requests.get(EFFIS_WMS, params=params, timeout=30)
    resp.raise_for_status()
    if not resp.headers.get("content-type", "").startswith("image"):
        raise RuntimeError(f"EFFIS error: {resp.text.strip()[:200]}")

    arr = np.array(Image.open(io.BytesIO(resp.content)))
    value = float(arr[grid // 2, grid // 2])

    if value < 0 or value > 200:
        return None
    # Disambiguate real zero from out-of-coverage. EFFIS renders nodata as
    # 0, so outside the Météo-France model domain the whole bbox is exactly
    # 0. Inside the domain, even a region with FWI ≈ 0 has tiny non-zero
    # neighbors from the model grid. If the entire window is strictly 0,
    # treat the sample as nodata.
    if value == 0 and float(arr.max()) == 0:
        return None
    return value
