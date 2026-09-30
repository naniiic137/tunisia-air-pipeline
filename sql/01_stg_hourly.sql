-- One row per city and hour, air quality and weather side by side.
-- Only complete past days are kept (the API also returns today's forecast).
CREATE OR REPLACE TABLE stg_hourly AS
WITH air AS (
    PIVOT (SELECT city, CAST(ts AS TIMESTAMP) AS ts, variable, value FROM raw_air)
    ON variable IN ('pm2_5', 'pm10', 'nitrogen_dioxide', 'ozone', 'dust', 'european_aqi')
    USING any_value(value)
), weather AS (
    PIVOT (SELECT city, CAST(ts AS TIMESTAMP) AS ts, variable, value FROM raw_weather)
    ON variable IN ('temperature_2m', 'wind_speed_10m', 'precipitation')
    USING any_value(value)
)
SELECT
    a.city,
    a.ts,
    CAST(a.ts AS DATE)            AS day,
    a.pm2_5,
    a.pm10,
    a.nitrogen_dioxide            AS no2,
    a.ozone                       AS o3,
    a.dust,
    a.european_aqi                AS eaqi,
    w.temperature_2m              AS temp_c,
    w.wind_speed_10m              AS wind_kmh,
    w.precipitation               AS rain_mm
FROM air a
LEFT JOIN weather w USING (city, ts)
WHERE CAST(a.ts AS DATE) < (SELECT max(CAST(ts AS DATE)) FROM raw_air);
