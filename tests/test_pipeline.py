"""Tests for every pipeline stage, on synthetic API responses (no network)."""
import json
from datetime import date, datetime, timedelta

import duckdb
import pytest

from airpipe import extract, load, quality, transform
from airpipe.extract import City

CITIES = [City("Alpha", 36.0, 10.0, "test"), City("Beta", 34.0, 9.0, "test"), City("Gamma", 33.0, 8.0, "test")]


def hours(start: date, days: int) -> list[str]:
    t0 = datetime(start.year, start.month, start.day)
    return [(t0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(days * 24)]


def air_payload(times, pm10_by_city, dust_share=0.1):
    out = []
    for pm10 in pm10_by_city:
        n = len(times)
        out.append({"hourly": {
            "time": times,
            "pm2_5": [pm10 * 0.4] * n, "pm10": [pm10] * n,
            "nitrogen_dioxide": [5.0 if i // 24 % 7 not in (5, 6) else 3.0 for i in range(n)],  # sat+sun lower
            "ozone": [80.0] * n, "dust": [pm10 * dust_share] * n, "european_aqi": [40] * n,
        }})
    return out


def weather_payload(times, n_cities):
    n = len(times)
    return [{"hourly": {"time": times, "temperature_2m": [25.0] * n, "wind_speed_10m": [10.0] * n,
                        "precipitation": [0.0] * n}} for _ in range(n_cities)]


def run(tmp_path, air, weather, today=None):
    (tmp_path / "air.json").write_text(json.dumps(air))
    (tmp_path / "weather.json").write_text(json.dumps(weather))
    con = duckdb.connect(":memory:")
    load.load(con, {"air": tmp_path / "air.json", "weather": tmp_path / "weather.json"}, CITIES)
    transform.transform(con)
    return con


# ---- extract -------------------------------------------------------------------------------

def test_build_url_lists_every_city_and_variable():
    url = extract.build_url(extract.AIR_URL, extract.AIR_VARS, CITIES)
    assert "latitude=36.0%2C34.0%2C33.0" in url and "longitude=10.0%2C9.0%2C8.0" in url
    assert "hourly=pm2_5%2Cpm10%2Cnitrogen_dioxide%2Cozone%2Cdust%2Ceuropean_aqi" in url
    assert "past_days=92" in url and "timezone=Africa%2FTunis" in url


def test_fetch_json_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(url, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("throttled")
        return Resp()

    monkeypatch.setattr(extract.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(extract.time, "sleep", lambda s: None)
    assert extract.fetch_json("http://x") == {"ok": True}
    assert calls["n"] == 3


# ---- load ----------------------------------------------------------------------------------

def test_flatten_maps_responses_to_cities_in_order():
    times = hours(date(2026, 1, 1), 1)
    rows = load.flatten(air_payload(times, [10, 20, 30]), CITIES)
    pm10 = {(c, v) for c, t, var, v in rows if var == "pm10"}
    assert pm10 == {("Alpha", 10), ("Beta", 20), ("Gamma", 30)}
    assert len(rows) == 3 * 24 * 6


def test_flatten_rejects_a_wrong_number_of_locations():
    with pytest.raises(ValueError, match="expected 3 locations"):
        load.flatten(air_payload(hours(date(2026, 1, 1), 1), [10, 20]), CITIES)


def test_flatten_rejects_ragged_arrays():
    payload = air_payload(hours(date(2026, 1, 1), 1), [10, 20, 30])
    payload[1]["hourly"]["pm10"] = payload[1]["hourly"]["pm10"][:-1]
    with pytest.raises(ValueError, match="Beta/pm10"):
        load.flatten(payload, CITIES)


# ---- transform -----------------------------------------------------------------------------

def test_models_build_daily_figures_and_who_flags(tmp_path):
    times = hours(date(2026, 1, 5), 8)  # 8 days; the last one is dropped as "today"
    con = run(tmp_path, air_payload(times, [60, 20, 30]), weather_payload(times, 3))
    days = con.execute("SELECT count(DISTINCT day) FROM daily").fetchone()[0]
    assert days == 7
    alpha = con.execute("SELECT pm10, pm2_5, pm10_over_who, pm2_5_over_who, hours FROM daily "
                        "WHERE city = 'Alpha' LIMIT 1").fetchone()
    assert alpha == (60.0, 24.0, True, True, 24)
    beta = con.execute("SELECT pm10_over_who, pm2_5_over_who FROM daily WHERE city = 'Beta' LIMIT 1").fetchone()
    assert beta == (False, False)  # 20 and 8 are under the WHO limits


def test_city_summary_ranks_worst_first(tmp_path):
    times = hours(date(2026, 1, 5), 4)
    con = run(tmp_path, air_payload(times, [60, 20, 30]), weather_payload(times, 3))
    ranking = con.execute("SELECT city FROM city_summary ORDER BY pm2_5_rank").fetchall()
    assert [r[0] for r in ranking] == ["Alpha", "Gamma", "Beta"]


def test_weekend_no2_is_lower(tmp_path):
    times = hours(date(2026, 1, 5), 15)  # Monday 5 January for two weeks
    con = run(tmp_path, air_payload(times, [20, 20, 20]), weather_payload(times, 3))
    wd, we = con.execute("SELECT no2_weekday, no2_weekend FROM no2_weekday_weekend WHERE city = 'Alpha'").fetchone()
    assert wd > we


def test_dust_episode_needs_three_cities_and_mostly_dust(tmp_path):
    times = hours(date(2026, 1, 5), 3)
    con = run(tmp_path, air_payload(times, [60, 70, 80], dust_share=0.6), weather_payload(times, 3))
    assert con.execute("SELECT count(*) FROM dust_episodes").fetchone()[0] == 2
    con = run(tmp_path, air_payload(times, [60, 70, 80], dust_share=0.1), weather_payload(times, 3))
    assert con.execute("SELECT count(*) FROM dust_episodes").fetchone()[0] == 0  # polluted, but not dust


# ---- quality -------------------------------------------------------------------------------

def failed(results):
    return {r["check"] for r in results if not r["passed"]}


def test_quality_passes_on_good_data(tmp_path):
    start = date.today() - timedelta(days=5)
    con = run(tmp_path, air_payload(hours(start, 6), [30, 20, 10]), weather_payload(hours(start, 6), 3))
    assert failed(quality.run_checks(con, expected_cities=3)) == set()


def test_quality_catches_negative_values_and_stale_data(tmp_path):
    start = date(2020, 1, 1)
    air = air_payload(hours(start, 3), [30, 20, 10])
    air[0]["hourly"]["pm10"][5] = -4.0
    con = run(tmp_path, air, weather_payload(hours(start, 3), 3))
    bad = failed(quality.run_checks(con, expected_cities=3))
    assert "pollutant values are physically plausible (0 to 2000 ug/m3)" in bad
    assert "data is fresh (latest day within 3 days)" in bad


def test_quality_catches_missing_cities_and_gaps(tmp_path):
    start = date.today() - timedelta(days=4)
    air = air_payload(hours(start, 5), [30, 20, 10])
    air[2]["hourly"]["pm2_5"] = [None] * len(air[2]["hourly"]["pm2_5"])
    con = run(tmp_path, air, weather_payload(hours(start, 5), 3))
    assert "every city has air quality data" in failed(quality.run_checks(con, expected_cities=4))
    assert "each city has at least 90% of hourly PM2.5 values" in failed(quality.run_checks(con, expected_cities=3))
