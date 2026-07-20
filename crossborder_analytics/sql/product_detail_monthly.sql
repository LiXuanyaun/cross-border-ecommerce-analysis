SELECT
    strftime('%Y-%m', order_date) AS month,
    COUNT(*) AS orders,
    COALESCE(SUM(quantity), 0) AS units,
    COALESCE(SUM(COALESCE(total_amount_base, total_amount)), 0.0) AS gmv,
    SUM(COALESCE(profit_amount_base, profit_amount)) AS profit,
    SUM(CASE WHEN returned = 1 THEN 1 ELSE 0 END) AS returned_orders
FROM orders
WHERE /* FILTERS */ AND product_id = :product_id
GROUP BY strftime('%Y-%m', order_date)
ORDER BY month;
