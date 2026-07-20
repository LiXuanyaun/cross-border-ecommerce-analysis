SELECT
    /* MARKET */ AS market,
    COALESCE(SUM(COALESCE(total_amount_base, total_amount)), 0.0) AS gmv,
    COUNT(*) AS orders,
    COUNT(DISTINCT customer_id) AS customers,
    SUM(COALESCE(profit_amount_base, profit_amount)) AS profit,
    AVG(delivery_time_days) AS delivery_mean,
    AVG(returned) AS return_rate
FROM orders
WHERE /* FILTERS */
GROUP BY /* MARKET */
ORDER BY gmv DESC;
