SELECT
    strftime('%Y-%m', order_date) AS month,
    COUNT(DISTINCT order_id) AS orders,
    COALESCE(SUM(quantity), 0) AS units,
    COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0) AS gmv,
    SUM(COALESCE(profit_amount_base, profit_amount)) AS profit,
    COUNT(DISTINCT CASE WHEN returned = 1 THEN order_id END) AS returned_orders
FROM orders
WHERE /* FILTERS */ AND product_id = :product_id
GROUP BY strftime('%Y-%m', order_date)
ORDER BY month;
