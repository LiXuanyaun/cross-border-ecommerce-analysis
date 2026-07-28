SELECT
    product_id,
    COUNT(DISTINCT order_id) AS orders,
    COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0) AS gmv,
    SUM(COALESCE(profit_amount_base, profit_amount)) AS profit
FROM orders
WHERE /* FILTERS */
GROUP BY product_id
HAVING SUM(COALESCE(profit_amount_base, profit_amount)) < 0
ORDER BY profit ASC;
