"""Extract: pull hourly air quality and weather for Tunisian cities from Open-Meteo.

One request per source covers every city (Open-Meteo accepts comma-separated coordinates),
so a full run is two HTTP calls. Raw responses are saved as JSON before any parsing, so a
run can be replayed offline and a bad transform never loses source data.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float
    note: str


CITIES = [
    City("Tunis", 36.806, 10.181, "capital, heaviest traffic"),
    City("Sfax", 34.740, 10.760, "second city, industrial port"),
    City("Sousse", 35.826, 10.636, "coastal, tourism"),
    City("Nabeul", 36.451, 10.735, "Cap Bon coast"),
    City("Bizerte", 37.274, 9.874, "northern port, refinery"),
    City("Kairouan", 35.678, 10.096, "inland plain"),
    City("Gabes", 33.881, 10.098, "phosphate chemical complex"),
    City("Gafsa", 34.425, 8.784, "phosphate mining basin"),
    City("Tozeur", 33.920, 8.134, "desert edge, Saharan dust"),
    City("Djerba", 33.807, 10.845, "island"),
]

AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_VARS = ["pm2_5", "pm10", "nitrogen_dioxide", "ozone", "dust", "european_aqi"]
WEATHER_VARS = ["temperature_2m", "wind_speed_10m", "precipitation"]
PAST_DAYS = 92  # the most history Open-Meteo keeps for these endpoints


def build_url(base: str, variables: list[str], cities: list[City] = CITIES) -> str:
    params = {
        "latitude": ",".join(f"{c.lat}" for c in cities),
        "longitude": ",".join(f"{c.lon}" for c in cities),
        "hourly": ",".join(variables),
        "past_days": PAST_DAYS,
        "forecast_days": 1,
        "timezone": "Africa/Tunis",
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


def fetch_json(url: str, retries: int = 3, backoff: float = 2.0) -> list | dict:
    """GET with a few retries and exponential backoff (the free API can briefly throttle)."""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(backoff * 2 ** attempt)
    raise RuntimeError("unreachable")


def extract(raw_dir: Path) -> dict[str, Path]:
    """Downloads both sources and writes them to raw_dir/{air,weather}.json."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, base, variables in (("air", AIR_URL, AIR_VARS), ("weather", WEATHER_URL, WEATHER_VARS)):
        payload = fetch_json(build_url(base, variables))
        path = raw_dir / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        out[name] = path
    return out
