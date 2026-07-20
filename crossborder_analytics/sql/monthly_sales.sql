SELECT
    strftime('%Y-%m', order_date) AS month,
    COALESCE(SUM(COALESCE(total_amount_base, total_amount)), 0.0) AS gmv,
    COUNT(*) AS orders,
    SUM(COALESCE(profit_amount_base, profit_amount)) AS profit
FROM orders
WHERE /* FILTERS */
GROUP BY strftime('%Y-%m', order_date)
ORDER BY month;
