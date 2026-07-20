SELECT
    COALESCE(SUM(COALESCE(total_amount_base, total_amount)), 0.0) AS gmv,
    COUNT(*) AS orders,
    COUNT(DISTINCT customer_id) AS customers,
    COALESCE(SUM(quantity), 0) AS units,
    COALESCE(SUM(COALESCE(profit_amount_base, profit_amount)), 0.0) AS profit_amount,
    COALESCE(SUM(CASE WHEN returned = 1 THEN 1 ELSE 0 END), 0) AS returned_orders
FROM orders
WHERE /* FILTERS */;
