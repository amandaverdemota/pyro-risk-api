#!/usr/bin/env python3
"""Query daily FWI (Fire Weather Index) from Copernicus EFFIS for a list of locations.

EFFIS exposes FWI as a WMS raster layer. The dedicated GetFeatureInfo query layer
(``mf010.query``) is configured server-side with unfilled template placeholders,
so we sample the value by requesting a small GetMap GeoTIFF centered on each
point and reading the center pixel.

Layer: ``mf010.fwi`` — Météo-France 10 km, daily forecast (today + ~3 days).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import requests
from PIL import Image

EFFIS_WMS = "https://maps.effis.emergency.copernicus.eu/effis"
LAYER = "mf010.fwi"
OUTPUT_CSV = Path(__file__).parent / "fwi_history.csv"

LOCATIONS: list[dict] = [
    {"name": "test_pithiviers", "lat": 48.40375094023455, "lon": 2.6823010616445297},
]

# EFFIS European FWI danger classes
FWI_CLASSES = [
    (5.2,   "very_low"),
    (11.2,  "low"),
    (21.3,  "moderate"),
    (38.0,  "high"),
    (50.0,  "very_high"),
    (float("inf"), "extreme"),
]


def fwi_class(value: float) -> str:
    for threshold, label in FWI_CLASSES:
        if value < threshold:
            return label
    return "extreme"


def query_fwi(lat: float, lon: float, target_date: date, layer: str = LAYER) -> float | None:
    """Sample the FWI value at (lat, lon) by reading the center pixel of a small
    GeoTIFF. Returns None on transport error or nodata."""
    # Native resolution is ~0.1°; use a 1° bbox sampled at 11×11 so the center
    # pixel is well-aligned and inside the data domain even near coasts.
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
        # WMS reports errors as XML with HTTP 200
        raise RuntimeError(f"EFFIS error: {resp.text.strip()[:200]}")

    arr = np.array(Image.open(io.BytesIO(resp.content)))
    value = float(arr[grid // 2, grid // 2])

    # FWI is non-negative; very small values come from interpolation noise
    if value < 0 or value > 200:
        return None
    return value


def run(locations: Iterable[dict], target_date: date, layer: str = LAYER) -> list[dict]:
    results = []
    for loc in locations:
        try:
            value = query_fwi(loc["lat"], loc["lon"], target_date, layer=layer)
            error = None
        except (requests.RequestException, RuntimeError) as exc:
            value = None
            error = str(exc)

        row = {
            "date": target_date.isoformat(),
            "name": loc["name"],
            "lat": loc["lat"],
            "lon": loc["lon"],
            "layer": layer,
            "fwi": round(value, 3) if value is not None else None,
            "class": fwi_class(value) if value is not None else None,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "error": error,
        }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False))
    return results


def write_csv_dedup(new_rows: list[dict], path: Path = OUTPUT_CSV) -> None:
    """Merge new_rows into the CSV, deduping on (date, name, layer). Newer rows win."""
    if not new_rows:
        return

    key = lambda r: (r["date"], r["name"], r["layer"])
    merged: dict[tuple, dict] = {}

    if path.exists():
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                merged[key(row)] = row

    for row in new_rows:
        merged[key(row)] = {k: ("" if v is None else v) for k, v in row.items()}

    rows_sorted = sorted(merged.values(), key=lambda r: (r["date"], r["name"]))
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(new_rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows_sorted)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch daily FWI from EFFIS for configured locations.")
    p.add_argument("--days", type=int, default=1,
                   help="Number of days back to fetch, ending today (default: 1).")
    p.add_argument("--start", type=date.fromisoformat, default=None,
                   help="Optional start date (YYYY-MM-DD). Overrides --days.")
    p.add_argument("--end", type=date.fromisoformat, default=None,
                   help="Optional end date (YYYY-MM-DD). Defaults to today.")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    today = datetime.now(timezone.utc).date()

    end = args.end or today
    start = args.start or (end - timedelta(days=args.days - 1))
    if start > end:
        sys.exit(f"start ({start}) is after end ({end})")

    all_rows: list[dict] = []
    day = start
    while day <= end:
        all_rows.extend(run(LOCATIONS, day))
        day += timedelta(days=1)

    write_csv_dedup(all_rows)
    sys.exit(0 if all(r["error"] is None for r in all_rows) else 1)
