SELECT
    /* MARKET */ AS market,
    COALESCE(NULLIF(TRIM(category), ''), '未标注品类') AS category,
    COUNT(DISTINCT order_id) AS orders,
    COALESCE(SUM(quantity), 0) AS units,
    COUNT(DISTINCT customer_id) AS customers,
    COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0) AS gmv,
    SUM(COALESCE(profit_amount_base, profit_amount)) AS profit,
    COUNT(DISTINCT CASE WHEN returned = 1 THEN order_id END) AS returned_orders
FROM orders
WHERE /* FILTERS */
GROUP BY /* MARKET */, COALESCE(NULLIF(TRIM(category), ''), '未标注品类')
ORDER BY market, orders DESC;
