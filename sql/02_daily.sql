-- Daily figures per city. WHO 2021 guideline limits for 24-hour means:
-- PM2.5 15 ug/m3, PM10 45 ug/m3.
CREATE OR REPLACE TABLE daily AS
SELECT
    city,
    day,
    count(pm2_5)                              AS hours,
    round(avg(pm2_5), 1)                      AS pm2_5,
    round(avg(pm10), 1)                       AS pm10,
    round(avg(no2), 1)                        AS no2,
    round(max(o3), 1)                         AS o3_max,
    round(avg(dust), 1)                       AS dust,
    round(avg(temp_c), 1)                     AS temp_c,
    round(max(wind_kmh), 1)                   AS wind_max_kmh,
    round(sum(rain_mm), 1)                    AS rain_mm,
    avg(pm2_5) > 15                           AS pm2_5_over_who,
    avg(pm10) > 45                            AS pm10_over_who,
    dayofweek(day) IN (0, 6)                  AS weekend
FROM stg_hourly
GROUP BY city, day;
