SELECT
    /* MARKET */ AS market,
    COUNT(DISTINCT order_id) AS orders,
    COUNT(DISTINCT customer_id) AS customers,
    COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0) AS gmv,
    SUM(COALESCE(profit_amount_base, profit_amount)) AS profit
FROM orders
WHERE /* FILTERS */ AND product_id = :product_id
GROUP BY /* MARKET */
ORDER BY gmv DESC;
