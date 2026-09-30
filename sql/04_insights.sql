-- Traffic signal: NO2 on weekdays vs weekends (traffic drops at weekends).
CREATE OR REPLACE TABLE no2_weekday_weekend AS
SELECT
    city,
    round(avg(no2) FILTER (WHERE NOT weekend), 1) AS no2_weekday,
    round(avg(no2) FILTER (WHERE weekend), 1)     AS no2_weekend,
    round(avg(no2) FILTER (WHERE NOT weekend) / nullif(avg(no2) FILTER (WHERE weekend), 0), 2) AS ratio
FROM daily
GROUP BY city;

-- Saharan dust episodes: days when at least 3 cities had PM10 above the WHO limit
-- and dust was the main contributor.
CREATE OR REPLACE TABLE dust_episodes AS
SELECT
    day,
    count(*) FILTER (WHERE pm10_over_who)        AS cities_over_who,
    round(max(pm10), 1)                          AS max_pm10,
    arg_max(city, pm10)                          AS worst_city,
    round(avg(dust / nullif(pm10, 0)) * 100, 0)  AS dust_share_pct
FROM daily
GROUP BY day
HAVING count(*) FILTER (WHERE pm10_over_who) >= 3 AND avg(dust / nullif(pm10, 0)) > 0.3
ORDER BY day;
