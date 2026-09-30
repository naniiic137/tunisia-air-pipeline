"""Builds the static dashboard (site/index.html) straight from the DuckDB models."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import plotly.graph_objects as go
import plotly.offline

PLOTLY_JS = f"https://cdn.jsdelivr.net/npm/plotly.js-dist-min@{plotly.offline.get_plotlyjs_version()}/plotly.min.js"
WHO_PM10, WHO_PM25 = 45, 15
HIGHLIGHT = {"Tozeur": "#d9822b", "Tunis": "#3d6fb6"}
MUTED = "rgba(140,150,165,0.45)"


def _rows(con, sql):
    r = con.execute(sql)
    cols = [d[0] for d in r.description]
    return [dict(zip(cols, row, strict=True)) for row in r.fetchall()]


def _layout(fig, height=420):
    fig.update_layout(height=height, margin=dict(l=10, r=20, t=10, b=40),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="Inter, Segoe UI, system-ui, sans-serif", size=13, color="#2b3440"),
                      legend=dict(orientation="h", y=-0.2))
    fig.update_xaxes(gridcolor="rgba(120,130,150,0.18)", zeroline=False)
    fig.update_yaxes(gridcolor="rgba(120,130,150,0.18)", zeroline=False)
    return fig


def _episodes(con):
    """Groups dust-episode days into (start, end) ranges for shading."""
    days = [r["day"] for r in _rows(con, "SELECT day FROM dust_episodes ORDER BY day")]
    ranges = []
    for d in days:
        if ranges and (d - ranges[-1][1]).days <= 2:
            ranges[-1][1] = d
        else:
            ranges.append([d, d])
    return ranges


def fig_timeline(con):
    daily = _rows(con, "SELECT city, day, pm10 FROM daily ORDER BY city, day")
    fig = go.Figure()
    for city in sorted({r["city"] for r in daily}, key=lambda c: c in HIGHLIGHT):
        pts = [r for r in daily if r["city"] == city]
        color = HIGHLIGHT.get(city, MUTED)
        fig.add_trace(go.Scatter(x=[p["day"] for p in pts], y=[p["pm10"] for p in pts], name=city, mode="lines",
                                 line=dict(color=color, width=2.6 if city in HIGHLIGHT else 1.2),
                                 hovertemplate=f"{city}<br>%{{x|%d %b}}: %{{y:.0f}} µg/m³<extra></extra>"))
    for start, end in _episodes(con):
        fig.add_vrect(x0=start, x1=end, fillcolor="#d9822b", opacity=0.10, line_width=0)
    fig.add_hline(y=WHO_PM10, line_dash="dash", line_color="#b33a3a",
                  annotation_text="WHO daily limit (45)", annotation_position="top left")
    fig.update_yaxes(title="Daily mean PM10 (µg/m³)")
    return _layout(fig, 440)


def fig_heatmap(con):
    daily = _rows(con, "SELECT d.city, d.day, d.pm10 FROM daily d JOIN city_summary s USING (city) "
                       "ORDER BY s.pm10_avg, d.day")
    cities = list(dict.fromkeys(r["city"] for r in daily))
    days = sorted({r["day"] for r in daily})
    grid = {(r["city"], r["day"]): r["pm10"] for r in daily}
    fig = go.Figure(go.Heatmap(
        z=[[grid.get((c, d)) for d in days] for c in cities], x=days, y=cities,
        colorscale=[[0, "#f1f5f9"], [0.3, "#fbd38d"], [0.6, "#e8743b"], [1, "#8b1e1e"]], zmin=0, zmax=100,
        colorbar=dict(title="PM10"), hovertemplate="%{y}, %{x|%d %b}: %{z:.0f} µg/m³<extra></extra>"))
    return _layout(fig, 380)


def fig_ranking(con):
    rows = _rows(con, "SELECT city, pct_days_pm10_over_who, days_pm10_over_who, days_pm2_5_over_who, days "
                      "FROM city_summary ORDER BY pct_days_pm10_over_who")
    fig = go.Figure(go.Bar(
        y=[r["city"] for r in rows], x=[r["pct_days_pm10_over_who"] for r in rows], orientation="h",
        marker_color=[HIGHLIGHT.get(r["city"], "#8aa0b8") for r in rows],
        customdata=[[r["days_pm10_over_who"], r["days"], r["days_pm2_5_over_who"]] for r in rows],
        hovertemplate="%{y}: PM10 over the WHO limit on %{customdata[0]} of %{customdata[1]} days"
                      "<br>PM2.5 over its limit on %{customdata[2]} days<extra></extra>"))
    fig.update_xaxes(title="Days with PM10 above the WHO daily limit (%)", ticksuffix="%")
    return _layout(fig, 400)


def fig_no2(con):
    rows = _rows(con, "SELECT city, no2_weekday, no2_weekend FROM no2_weekday_weekend ORDER BY no2_weekday")
    fig = go.Figure([
        go.Bar(y=[r["city"] for r in rows], x=[r["no2_weekend"] for r in rows], name="Weekend", orientation="h",
               marker_color="#b8c4d2", hovertemplate="%{y} weekend: %{x:.1f} µg/m³<extra></extra>"),
        go.Bar(y=[r["city"] for r in rows], x=[r["no2_weekday"] for r in rows], name="Weekday", orientation="h",
               marker_color="#3d6fb6", hovertemplate="%{y} weekday: %{x:.1f} µg/m³<extra></extra>"),
    ])
    fig.update_layout(barmode="group")
    fig.update_xaxes(title="Mean NO₂ (µg/m³)")
    return _layout(fig, 420)


def fig_map(con):
    rows = _rows(con, "SELECT c.city, c.lat, c.lon, c.note, s.pm10_avg FROM cities c JOIN city_summary s USING (city)")
    fig = go.Figure(go.Scattergeo(
        lat=[r["lat"] for r in rows], lon=[r["lon"] for r in rows], text=[r["city"] for r in rows],
        mode="markers+text", textposition="middle right",
        marker=dict(size=[r["pm10_avg"] * 0.8 for r in rows], color=[r["pm10_avg"] for r in rows],
                    colorscale=[[0, "#fbd38d"], [1, "#8b1e1e"]], line=dict(width=1, color="white")),
        customdata=[[r["note"], r["pm10_avg"]] for r in rows],
        hovertemplate="%{text} (%{customdata[0]})<br>mean PM10 %{customdata[1]:.1f} µg/m³<extra></extra>"))
    fig.update_geos(scope="africa", lataxis_range=[30, 38], lonaxis_range=[7, 12.5], showcountries=True,
                    countrycolor="#9aa7b8", showland=True, landcolor="#eef1f5", showocean=True,
                    oceancolor="#dbe7f3", resolution=50)
    return _layout(fig, 460)


def summary(con) -> dict:
    s = _rows(con, "SELECT min(day) AS first_day, max(day) AS last_day, count(DISTINCT day) AS days, "
                   "count(DISTINCT city) AS cities FROM daily")[0]
    worst = _rows(con, "SELECT city, pct_days_pm10_over_who, worst_day, worst_day_pm10 FROM city_summary "
                       "ORDER BY pct_days_pm10_over_who DESC LIMIT 1")[0]
    s["dust_episode_days"] = _rows(con, "SELECT count(*) AS n FROM dust_episodes")[0]["n"]
    s["all_cities_over_who_days"] = _rows(con, "SELECT count(*) AS n FROM dust_episodes "
                                                "WHERE cities_over_who = (SELECT count(*) FROM cities)")[0]["n"]
    s["worst_city"] = worst
    s["tunis_no2"] = _rows(con, "SELECT no2_weekday, no2_weekend FROM no2_weekday_weekend WHERE city = 'Tunis'")[0]
    return s


def _div(fig):
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False, "responsive": True})


def build(con: duckdb.DuckDBPyConnection, out: Path, checks: list[dict], started: datetime) -> None:
    s = summary(con)
    w = s["worst_city"]
    tiles = [
        (f"{s['cities']}", f"cities, {s['days']} days of hourly data"),
        (f"{s['dust_episode_days']}", "days of Saharan dust over at least 3 cities"),
        (f"{s['all_cities_over_who_days']}", "days when every city broke the WHO PM10 limit"),
        (f"{w['pct_days_pm10_over_who']:.0f}%", f"of days above the PM10 limit in {w['city']}, the worst city"),
    ]
    tiles_html = "".join(f'<div class="tile"><b>{html.escape(v)}</b><span>{html.escape(t)}</span></div>'
                         for v, t in tiles)
    tn = s["tunis_no2"]
    sections = [
        ("Daily PM10 across Tunisia",
         "Shaded bands are Saharan dust episodes. Dust lifts particle levels in every city at once, far more than "
         "any local source.", fig_timeline(con)),
        ("Every city, every day",
         "Daily mean PM10, cities sorted from cleanest (top) to most polluted (bottom).", fig_heatmap(con)),
        ("Which cities break the limit most often",
         f"Share of days above the WHO 2021 daily PM10 guideline (45 µg/m³). {w['city']}, on the edge of the "
         f"Sahara, peaked at {w['worst_day_pm10']:.0f} µg/m³ on {w['worst_day']:%d %B}.", fig_ranking(con)),
        ("The traffic signal: NO₂ drops at weekends",
         f"Nitrogen dioxide comes mostly from traffic, so it's higher on weekdays in every city. Tunis has by far "
         f"the most: {tn['no2_weekday']} µg/m³ on weekdays vs {tn['no2_weekend']} at weekends.", fig_no2(con)),
        ("Where the cities are", "Bubble size and colour show mean PM10 over the period.", fig_map(con)),
    ]
    body = "".join(f"<section><h2>{html.escape(t)}</h2><p>{html.escape(d)}</p>{_div(f)}</section>"
                   for t, d, f in sections)
    checks_html = "".join(
        f'<li class="{"ok" if c["passed"] else c["severity"]}">{"✓" if c["passed"] else "✗"} {html.escape(c["check"])}</li>'
        for c in checks)
    page = TEMPLATE.format(
        tiles=tiles_html, body=body, plotly_js=PLOTLY_JS, checks=checks_html,
        first=f"{s['first_day']:%d %b %Y}", last=f"{s['last_day']:%d %b %Y}",
        run=started.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC"),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tunisia Air Quality</title>
<meta name="description" content="Daily air quality and Saharan dust across 10 Tunisian cities, rebuilt every day by an automated data pipeline.">
<script src="{plotly_js}"></script>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --text:#2b3440; --muted:#667085; --accent:#d9822b; --line:#e4e7ec; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font-family:Inter, "Segoe UI", system-ui, sans-serif; line-height:1.55; }}
header, main, footer {{ max-width:1040px; margin:0 auto; padding-left:16px; padding-right:16px; }}
header {{ padding-top:48px; padding-bottom:28px; }}
.kicker {{ color:var(--accent); font-weight:600; letter-spacing:.04em; text-transform:uppercase; font-size:13px; margin:0 0 8px; }}
h1 {{ font-size:clamp(28px, 5vw, 40px); margin:0 0 10px; line-height:1.15; }}
header p {{ color:var(--muted); max-width:720px; margin:0; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:12px; margin-bottom:24px; }}
.tile, section, .health {{ background:var(--card); border:1px solid var(--line); border-radius:12px; }}
.tile {{ padding:18px; }}
.tile b {{ display:block; font-size:28px; }}
.tile span {{ color:var(--muted); font-size:14px; }}
section {{ padding:22px 20px 8px; margin-bottom:18px; }}
section h2, .health h2 {{ margin:0 0 6px; font-size:20px; }}
section p {{ margin:0 0 8px; color:var(--muted); max-width:760px; }}
.health {{ padding:20px; margin-bottom:18px; }}
.health ul {{ list-style:none; padding:0; margin:8px 0 0; columns:2; column-gap:24px; }}
.health li {{ font-size:14px; margin-bottom:4px; break-inside:avoid; }}
.health li.ok {{ color:#2f7d4f; }} .health li.error {{ color:#b33a3a; }} .health li.warn {{ color:#a86a00; }}
footer {{ padding-bottom:48px; color:var(--muted); font-size:14px; }}
footer a {{ color:inherit; }}
@media (max-width:640px) {{ .health ul {{ columns:1; }} }}
</style>
</head>
<body>
<header>
  <p class="kicker">Automated data pipeline · updated daily</p>
  <h1>Air quality across Tunisia</h1>
  <p>Hourly particles, nitrogen dioxide and Saharan dust for 10 cities from {first} to {last}, rebuilt every day by a
  pipeline: extract from the Open-Meteo API, load into DuckDB, transform in SQL, run data-quality checks, then publish.</p>
</header>
<main>
<div class="tiles">{tiles}</div>
{body}
<div class="health">
  <h2>Pipeline health</h2>
  <p style="color:var(--muted);margin:0">Last run: {run}. Every check below must pass before the dashboard is published.</p>
  <ul>{checks}</ul>
</div>
</main>
<footer>
  <p><b>Data.</b> <a href="https://open-meteo.com/">Open-Meteo</a> (CC BY 4.0). Air quality comes from the
  Copernicus Atmosphere Monitoring Service (CAMS) global model, about 40 km per grid cell, so it shows regional
  pollution and dust well but can miss very local sources such as a single factory. It is modelled data, not
  readings from ground monitoring stations. Contains modified Copernicus Atmosphere Monitoring Service information.</p>
  <p><b>Limits.</b> WHO 2021 air quality guidelines, 24-hour means: PM2.5 15 µg/m³, PM10 45 µg/m³.</p>
</footer>
</body>
</html>
"""
