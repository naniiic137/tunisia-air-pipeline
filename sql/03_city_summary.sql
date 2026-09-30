-- One row per city over the whole window, ranked from worst to best PM2.5.
CREATE OR REPLACE TABLE city_summary AS
SELECT
    d.city,
    c.note,
    count(*)                                              AS days,
    round(avg(d.pm2_5), 1)                                AS pm2_5_avg,
    round(avg(d.pm10), 1)                                 AS pm10_avg,
    round(avg(d.no2), 1)                                  AS no2_avg,
    sum(d.pm2_5_over_who::INT)                            AS days_pm2_5_over_who,
    sum(d.pm10_over_who::INT)                             AS days_pm10_over_who,
    round(100.0 * sum(d.pm10_over_who::INT) / count(*), 1) AS pct_days_pm10_over_who,
    arg_max(d.day, d.pm10)                                AS worst_day,
    max(d.pm10)                                           AS worst_day_pm10,
    rank() OVER (ORDER BY avg(d.pm2_5) DESC)              AS pm2_5_rank
FROM daily d
JOIN cities c USING (city)
GROUP BY d.city, c.note;
